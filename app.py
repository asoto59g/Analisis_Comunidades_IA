import streamlit as st
import folium
from folium.plugins import Draw
from streamlit_folium import st_folium, folium_static
from shapely.geometry import shape
import sys
import os

# Asegurar que la ruta src esté en el sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

from data_fetcher import fetch_street_network_from_polygon, generate_sample_points, fetch_mapillary_images, fetch_pois_from_polygon
from cv_analyzer import mock_analyze_community, analyze_real_mapillary_images
from map_generator import create_community_map
import geopandas as gpd

st.set_page_config(page_title="Análisis Comunitario", layout="wide")

st.title("🏙️ Análisis de Servicios Comunitarios (Open Source)")
st.markdown("""
Esta herramienta analiza la infraestructura urbana utilizando redes viales de OpenStreetMap e imágenes a nivel de calle. 
Permite identificar **comercios, paradas de buses, parques recreativos y la condición de las vías**.
""")

with st.sidebar:
    st.header("Configuración de Mapillary")
    mapillary_token = st.text_input("Token de Mapillary (Client Token)", type="password", help="Obtén tu token gratuito en mapillary.com/dashboard/developers")
    if mapillary_token:
        st.success("Token ingresado. Se usarán imágenes reales de la comunidad.")
    else:
        st.warning("Sin token. Se usarán imágenes de prueba genéricas.")

st.markdown("### 1. Selecciona el Área de Estudio")
st.info("Utiliza las herramientas de dibujo (polígono o rectángulo) en el mapa de abajo para encerrar la zona exacta que deseas analizar.")

# Crear el mapa base para dibujar
m_draw = folium.Map(location=[9.9281, -84.0907], zoom_start=13, tiles="CartoDB positron") # San Jose por defecto
draw = Draw(
    export=False,
    position="topleft",
    draw_options={
        "polyline": False,
        "poly": False,
        "circle": False,
        "polygon": True,
        "marker": False,
        "circlemarker": False,
        "rectangle": True,
    },
)
draw.add_to(m_draw)

# Renderizar el mapa de dibujo y capturar la salida
output = st_folium(m_draw, width=1000, height=400, key="draw_map")

st.markdown("---")

# Verificar si el usuario ha dibujado algo
if output["all_drawings"] is not None and len(output["all_drawings"]) > 0:
    # Tomar la última geometría dibujada
    drawn_geojson = output["all_drawings"][-1]["geometry"]
    # Convertir a polígono de shapely
    drawn_polygon = shape(drawn_geojson)
    
    st.success("Área seleccionada correctamente.")
    
    analizar_btn = st.button("Ejecutar Análisis en el Área Seleccionada")

    if analizar_btn:
        with st.spinner("Descargando red vial para el polígono seleccionado desde OpenStreetMap..."):
            edges_gdf, error = fetch_street_network_from_polygon(drawn_polygon)
            
        if error:
            st.error(f"Error al descargar la comunidad: {error}")
        else:
            st.success("✅ Red vial descargada correctamente.")
            
            with st.spinner("Descargando comercios y servicios reales (OSM POIs)..."):
                pois_gdf, poi_error = fetch_pois_from_polygon(drawn_polygon)
                if not pois_gdf.empty:
                    st.write(f"- Se encontraron {len(pois_gdf)} comercios y servicios registrados en OpenStreetMap.")
                else:
                    st.write("- No se encontraron comercios registrados en OSM para esta zona.")
            
            with st.spinner("Conectando con Mapillary y ejecutando análisis de Visión por Computadora..."):
                if mapillary_token:
                    # Modo real con Mapillary
                    bounds = edges_gdf.total_bounds
                    bbox_str = f"{bounds[0]},{bounds[1]},{bounds[2]},{bounds[3]}"
                    
                    mapillary_gdf, mapillary_error = fetch_mapillary_images(bbox_str, client_id=mapillary_token)
                    
                    if not mapillary_gdf.empty:
                        st.write(f"- Se encontraron {len(mapillary_gdf)} fotografías reales en el área seleccionada.")
                        analysis_results = analyze_real_mapillary_images(mapillary_gdf)
                    else:
                        if mapillary_error:
                            st.error(f"❌ Error al conectar con Mapillary: {mapillary_error}")
                        st.warning("No se pudieron procesar fotografías reales en esta área. Mostrando resultados de simulación.")
                        points_gdf = generate_sample_points(edges_gdf)
                        analysis_results = mock_analyze_community(points_gdf)
                else:
                    # Modo simulado sin token
                    st.write("- Generando puntos de muestreo en la red...")
                    points_gdf = generate_sample_points(edges_gdf)
                    analysis_results = mock_analyze_community(points_gdf)
                
            st.success("✅ Análisis completado.")
            
            # Dashboard Results
            st.header("📊 Resultados del Análisis")
            
            col1, col2, col3, col4 = st.columns(4)
            
            num_comercios_ia = analysis_results['comercio'].sum()
            num_comercios_osm = len(pois_gdf) if not pois_gdf.empty else 0
            
            num_paradas = int(analysis_results['parada_bus'].sum()) if 'parada_bus' in analysis_results.columns else 0
            num_parques = int(analysis_results['parque_recreativo'].sum()) if 'parque_recreativo' in analysis_results.columns else 0
            
            # Estado de vías
            vias_totales = len(analysis_results)
            vias_buenas = len(analysis_results[analysis_results['condicion_via'] == 'Buena']) if 'condicion_via' in analysis_results.columns else 0
            porcentaje_vias_buenas = (vias_buenas / vias_totales) * 100 if vias_totales > 0 else 0
            
            col1.metric("Comercios (IA + OSM)", int(num_comercios_ia + num_comercios_osm))
            col2.metric("Paradas de Bus", num_paradas)
            col3.metric("Parques Recreativos", num_parques)
            col4.metric("Vías en Buen Estado", f"{porcentaje_vias_buenas:.1f}%")
            
            if vias_totales > 0 and (num_paradas + num_parques) == 0:
                st.warning("⚠️ La IA analizó las imágenes pero no encontró paradas o parques claros en estas fotografías específicas.")
            
            st.subheader("🗺️ Mapa de Infraestructura Detectada")
            mapa_resultado = create_community_map(edges_gdf, analysis_results, pois_gdf)
            folium_static(mapa_resultado, width=1000, height=500)
            
            st.info("""
            **Nota sobre despliegue y Mapillary:** 
            Actualmente, la herramienta está configurada para simular el análisis visual de las calles extraídas de OSM. 
            Si el equipo documenta fotográficamente las zonas faltantes usando la app de Mapillary, estas imágenes estarán 
            disponibles globalmente en cuestión de horas. Posteriormente, al añadir un `Client ID` de Mapillary en el código (`src/data_fetcher.py`),
            las imágenes reales serán procesadas por el modelo de IA.
            """)
            
            # Exportar datos
            st.markdown("### 📥 Exportar Resultados")
            st.write("Puedes descargar los puntos detectados en formato GeoJSON, el cual es compatible con Google Drive (Google My Maps), QGIS, ArcGIS y otros sistemas de información geográfica.")
            
            # Convertir resultados a GeoDataFrame
            gdf_export = gpd.GeoDataFrame(
                analysis_results, 
                geometry=gpd.points_from_xy(analysis_results.lon, analysis_results.lat),
                crs="EPSG:4326"
            )
            
            # Crear botón de descarga
            geojson_data = gdf_export.to_json()
            st.download_button(
                label="Descargar Capas (GeoJSON)",
                data=geojson_data,
                file_name="analisis_comunidad_servicios.geojson",
                mime="application/geo+json"
            )
else:
    st.warning("Por favor, dibuja un polígono o rectángulo en el mapa superior para comenzar.")
