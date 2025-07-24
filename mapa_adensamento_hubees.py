#!pip install fiona --quiet

import geopandas as gpd
import pandas as pd
import folium
import fiona
import numpy as np
from shapely.geometry import box, Point
from folium import FeatureGroup, GeoJson, GeoJsonTooltip, Marker, DivIcon
from branca.element import MacroElement
from jinja2 import Template


# === CONFIGURAÇÃO ===
KML_PATH = "mapa_hubees.kml"
CSV_PATH = "Dados região Geral.csv"
STEP = 200
OUTPUT_HTML = "mapa_densidade_hubees.html"

# === MAPA BASE ===
mapa = folium.Map(location=[-23.561684, -46.655981], zoom_start=14, tiles="CartoDB positron")
grupo_bairros_individuais = {}
group_zonas_mortas = FeatureGroup(name="Zonas Mortas", show=False)
group_quadrantes = FeatureGroup(name="Quadrantes", show=True)
group_eps_netpark = FeatureGroup(name="EPs Netpark", show=True)
group_eps_outros = FeatureGroup(name="EPs Não Netpark", show=True)
group_quadrantes_zm = FeatureGroup(name="Quadrantes ZM", show=True)
group_quadrantes_ep = FeatureGroup(name="Quadrantes com EP", show=True)
group_limites_bairros = FeatureGroup(name="Limites", show=True)
group_numero_quadrante = FeatureGroup(name="Número Quadrante", show=False)

# === LER KML ===
layers = fiona.listlayers(KML_PATH)
gdf_bairros = []
gdf_zonas_mortas = []

for layer in layers:
    gdf = gpd.read_file(KML_PATH, driver="KML", layer=layer).to_crs("EPSG:4326")
    gdf = gdf[gdf["Name"].notna()]

    for _, row in gdf.iterrows():
        name = str(row["Name"]).strip().lower()
        if name == "zm":
            gdf_zonas_mortas.append(gpd.GeoDataFrame([row], crs="EPSG:4326"))
        else:
            gdf_bairros.append(gpd.GeoDataFrame([row], crs="EPSG:4326"))

gdf_all_bairros = gpd.GeoDataFrame(pd.concat(gdf_bairros, ignore_index=True), crs="EPSG:4326")
gdf_all_zm = gpd.GeoDataFrame(pd.concat(gdf_zonas_mortas, ignore_index=True), crs="EPSG:4326")

# === DESENHAR POLÍGONOS DOS BAIRROS E ZM
GeoJson(
    gdf_all_bairros,
    style_function=lambda x: {"color": "#FFA500", "weight": 2, "fillOpacity": 0},
    tooltip=GeoJsonTooltip(fields=["Name"])
).add_to(group_limites_bairros)

GeoJson(
    gdf_all_zm,
    style_function=lambda x: {
        "color": "#000000",
        "weight": 2,
        "fillColor": "#666666",
        "fillOpacity": 0.4
    },
    tooltip=GeoJsonTooltip(fields=["Name"])
).add_to(group_zonas_mortas)

# === LER E PREPARAR EPs
df = pd.read_csv(CSV_PATH, sep=',')
df['LAT'] = pd.to_numeric(df['LAT'], errors='coerce')
df['LNG'] = pd.to_numeric(df['LNG'], errors='coerce')
df = df.dropna(subset=['LAT', 'LNG'])
df['geometry'] = df.apply(lambda row: Point(row['LNG'], row['LAT']), axis=1)
gdf_eps = gpd.GeoDataFrame(df, geometry='geometry', crs='EPSG:4326')

eps_dentro = gdf_eps[gdf_eps.geometry.within(gdf_all_bairros.unary_union)]

# === GERAR QUADRANTES AJUSTADOS POR INTERSECÇÃO
gdf_union = gpd.GeoDataFrame(geometry=[gdf_all_bairros.unary_union], crs="EPSG:4326")
gdf_union_3857 = gdf_union.to_crs(epsg=3857)
pol_3857 = gdf_union_3857.geometry.iloc[0]
minx, miny, maxx, maxy = pol_3857.bounds

grid_cells = []
for x in np.arange(minx, maxx, STEP):
    for y in np.arange(miny, maxy, STEP):
        cell = box(x, y, x + STEP, y + STEP)
        intersecao = cell.intersection(pol_3857)
        if not intersecao.is_empty:
            grid_cells.append(intersecao)

gdf_quadrantes = gpd.GeoDataFrame(geometry=grid_cells, crs="EPSG:3857").to_crs("EPSG:4326")

GeoJson(
    gdf_quadrantes,
    style_function=lambda x: {
        "color": "#333333",
        "weight": 0.1,
        "fillOpacity": 0
    }
).add_to(group_quadrantes)

# === MARCAR ZONAS MORTAS
gdf_all_zm_union = gpd.GeoDataFrame(geometry=[gdf_all_zm.unary_union], crs="EPSG:4326")

# === ENUMERAR QUADRANTES POR BAIRRO
estatisticas_bairros = []

for _, bairro_row in gdf_all_bairros.iterrows():
    bairro_nome = bairro_row['Name']

    #grupo_bairro = folium.FeatureGroup(name=f"Bairro: {bairro_nome.title()}", show=True)
    grupo_bairro = folium.FeatureGroup(name=bairro_nome.replace("_", " ").title(), show=True)
    grupo_bairros_individuais[bairro_nome] = grupo_bairro

    gdf_bairro_geom = gpd.GeoDataFrame(geometry=[bairro_row.geometry], crs="EPSG:4326")

    folium.GeoJson(
        gdf_bairro_geom,
        style_function=lambda x: {"color": "#FFA500", "weight": 2, "fillOpacity": 0},
        tooltip=GeoJsonTooltip(fields=[])
    ).add_to(grupo_bairro)

    eps_bairro = eps_dentro[eps_dentro.geometry.within(bairro_row.geometry)]

    for _, row in eps_bairro.iterrows():
        nome = row.get('NOME', 'EP')
        lat = row['LAT']
        lng = row['LNG']
        netpark = str(row.get('EP_NETPARK', '')).strip().lower() in ['netpark', 'sim', 'true', '1']
        cor = "blue" if netpark else "green"
        folium.Marker(
            location=[lat, lng],
            tooltip=nome,
            icon=folium.Icon(icon="car", prefix="fa", color=cor)
        ).add_to(grupo_bairro)

    grupo_bairro.add_to(mapa)
    gdf_bairro_geom = gpd.GeoDataFrame(geometry=[bairro_row.geometry], crs="EPSG:4326")

    quads_do_bairro = gdf_quadrantes[gdf_quadrantes.geometry.intersects(bairro_row.geometry)]
    eps_no_bairro = eps_dentro[eps_dentro.geometry.within(bairro_row.geometry)]

    quads_ep = gpd.sjoin(quads_do_bairro, eps_no_bairro, how="inner", predicate="contains")
    ids_ep = quads_ep.index.unique()
    quads_com_ep = quads_do_bairro.loc[ids_ep]

    quads_dentro_zm = quads_do_bairro[quads_do_bairro.geometry.intersects(gdf_all_zm_union.geometry.iloc[0])]
    quads_zm_validos = quads_dentro_zm.drop(index=quads_com_ep.index, errors='ignore')

    total = len(quads_do_bairro)
    ep = len(quads_com_ep)
    zm = len(quads_zm_validos)

    total_valido = total - zm
    estatisticas_bairros.append(f"<b>{bairro_nome.title()}:</b> Quadrantes [{total}], Com EP [{ep}], Zona Morta [{zm}]")
    estatisticas_bairros.append(f"<b>{bairro_nome.title()}:</b> Quadrantes Válidos [{total_valido}], Com EP [{ep}], Zona Morta [{zm}], Total EPs [{len(eps_bairro)}]")

    contador = 1  # Contador único por bairro

    for row in quads_do_bairro.itertuples():
        geom = row.geometry

        # Verifica se é zona morta
        if row.Index in quads_zm_validos.index:
            color = "#666666"
            fill_opacity = 0.5
        # Verifica se é quadrante com EP
        elif row.Index in quads_com_ep.index:
            color = "#72AF26"
            fill_opacity = 0.5
        else:
            color = "#ffffff"     # branco (sem EP e sem ZM)
            fill_opacity = 0      # sem preenchimento

        folium.GeoJson(
            geom,
            style_function=lambda x, c=color, f=fill_opacity: {
                "color": "#333333",
                "weight": 1,
                "fillColor": c,
                "fillOpacity": f
            }
        ).add_to(grupo_bairro)

        # Numerar todos os quadrantes
        centro = geom.centroid
        folium.Marker(
            location=[centro.y, centro.x],
            icon=DivIcon(html=f"<div style='color:#363636;font-size:9px'><b>{contador}</b></div>")
        ).add_to(group_numero_quadrante)
        contador += 1


# === ADICIONAR GRUPOS AO MAPA (na ordem correta para aparecer no controle de camadas)
group_limites_bairros.add_to(mapa)
group_numero_quadrante.add_to(mapa)
group_zonas_mortas.add_to(mapa)

# LayerControl DEVE vir por último
folium.LayerControl(collapsed=False).add_to(mapa)

# Substitui o título padrão da LayerControl por "Filtros"
custom_css = """
<style>
    .leaflet-control-layers-base label span {
        display: none !important;
    }

    .leaflet-control-layers-base:before {
        content: "Mostrar";
        font-weight: bold;
        display: block;
        margin-bottom: 5px;
        color: #333;
    }

    .leaflet-control-layers-list label:nth-child(6)::before {
        content: "────────────";
        display: block;
        margin: 8px 0 4px 0;
        color: #aaa;
        font-size: 10px;
        text-align: center;
    }
</style>
"""

mapa.get_root().header.add_child(folium.Element(custom_css))

# === LEGENDA SUPERIOR ESQUERDA
estatisticas_html = "<br>".join(estatisticas_bairros)
legend_html = f"""
<div id="legend" style="
    position: fixed;
    top: 15px;
    left: 15px;
    z-index: 9999;
    background-color: rgba(255, 255, 255, 0.96);
    padding: 15px;
    border-radius: 10px;
    font-family: 'Segoe UI', sans-serif;
    max-height: 800px;
    overflow-y: auto;
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
    width: 300px;
">
    <div style="text-align:right; margin-top: -10px;">
        <a href='#' onclick="document.getElementById('legend').style.display='none';" style="text-decoration:none;font-weight:bold;color:#666;">✖</a>
    </div>
    <h4 style="margin:5px 0 15px 0; color:#333; font-size:16px;">📊 Visão Geral por Zona Prioriária</h4>
"""

for linha in estatisticas_bairros:
    if "Total EPs" not in linha:
        continue  # ignora a linha incompleta
    nome = linha.split(":")[0].strip().replace("_", " ").title()
    valores = linha.split(":")[1]
    #quad = int(valores.split("[")[1].split("]")[0])
    quad_valido = int(valores.split("[")[1].split("]")[0])
    ep = int(valores.split("[")[2].split("]")[0])
    zm = int(valores.split("[")[3].split("]")[0])
    total_eps = int(valores.split("[")[4].split("]")[0])
    itl = round((ep / quad_valido) * 100) if quad_valido > 0 else 0
    #itl = round((ep / quad) * 100) if quad > 0 else 0


    legend_html += f"""
    <div style="
        background:#f9f9f9;
        border-radius:8px;
        padding:10px 12px;
        margin-bottom:10px;
        border-left:5px solid #4CAF50;
    ">
        <div style="font-size:15px; font-weight:600; margin-bottom:6px;">
          {nome} - <span style="color:#000000;font-weight:500;">ILT {itl}%</span>
        </div>

        <div style="font-size:13px; color:#333;">
              <b>Total Quadrantes Válidos:</b> {quad_valido}<br>
              <span style="display:inline-block; width:12px; height:12px; background-color:#72AF26; margin-right:6px; border-radius:2px;"></span>
              <b>Com EP:</b> {ep}<br>
              <span style="display:inline-block; width:12px; height:12px; background-color:#666; margin-right:6px; border-radius:2px;"></span>
              <b>Zona Morta:</b> {zm}<br>

            <b>Total EPs:</b> {total_eps}
        </div>
    </div>
    """

legend_html += "</div>"
mapa.get_root().html.add_child(folium.Element(legend_html))


# === SALVAR
mapa.save(OUTPUT_HTML)
#mapa
