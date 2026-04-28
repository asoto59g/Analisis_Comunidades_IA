import folium
import geopandas as gpd

def create_community_map(edges_gdf, analysis_df=None, pois_gdf=None):
    """
    Genera un mapa base con la red vial y opcionalmente los puntos analizados.
    """
    # Calcular centro para el mapa
    bounds = edges_gdf.total_bounds # [minx, miny, maxx, maxy]
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2
    
    m = folium.Map(location=[center_lat, center_lon], zoom_start=15, tiles="CartoDB positron")
    
    # Añadir red vial
    folium.GeoJson(
        edges_gdf,
        style_function=lambda x: {'color': '#3388ff', 'weight': 2}
    ).add_to(m)
    
    # Añadir POIs de OSM si existen
    if pois_gdf is not None and not pois_gdf.empty:
        osm_layer = folium.FeatureGroup(name="Servicios Reales (OSM)")
        for idx, row in pois_gdf.iterrows():
            name = row.get('name', 'Servicio sin nombre')
            amenity = str(row.get('amenity', ''))
            shop = str(row.get('shop', ''))
            
            # Lógica de Iconos y Colores
            color = 'orange'
            icon = 'shopping-cart'
            
            if 'school' in amenity or 'university' in amenity or 'college' in amenity:
                color, icon = 'blue', 'graduation-cap'
            elif 'hospital' in amenity or 'clinic' in amenity or 'doctors' in amenity:
                color, icon = 'red', 'medkit'
            elif 'pharmacy' in amenity:
                color, icon = 'green', 'plus-square'
            elif 'fire_station' in amenity:
                color, icon = 'darkred', 'fire-extinguisher'
            elif 'bank' in amenity or 'atm' in amenity:
                color, icon = 'black', 'university'
            elif 'bus_stop' in str(row.get('highway', '')):
                color, icon = 'cadetblue', 'bus'
            
            folium.Marker(
                location=[row.geometry.y, row.geometry.x],
                icon=folium.Icon(color=color, icon=icon, prefix='fa'),
                popup=f"<b>{name}</b><br>Tipo: {amenity if amenity != 'nan' else shop}"
            ).add_to(osm_layer)
        osm_layer.add_to(m)

    # Si hay resultados de análisis, agregarlos
    if analysis_df is not None and not analysis_df.empty:
        # Convertir a GeoDataFrame si no lo es
        if not isinstance(analysis_df, gpd.GeoDataFrame):
            analysis_gdf = gpd.GeoDataFrame(
                analysis_df, 
                geometry=gpd.points_from_xy(analysis_df.lon, analysis_df.lat),
                crs="EPSG:4326"
            )
        else:
            analysis_gdf = analysis_df

        # Proyectar para cálculos en metros (usar una proyección local o 3857 para aproximación)
        analysis_meters = analysis_gdf.to_crs(epsg=3857)
        
        # Agrupación espacial simple: Redondear coordenadas a 50 metros para "binning"
        # Esto agrupa puntos cercanos en una cuadrícula de 50x50m
        analysis_meters['grid_x'] = (analysis_meters.geometry.x // 50) * 50
        analysis_meters['grid_y'] = (analysis_meters.geometry.y // 50) * 50
        
        # Agrupar por la cuadrícula
        aggregated = analysis_meters.groupby(['grid_x', 'grid_y']).agg({
            'roughness_score': 'mean',
            'lat': 'first',
            'lon': 'first',
            'image_url': 'first',
            'comercio': 'max',
            'parada_bus': 'max',
            'parque_recreativo': 'max'
        }).reset_index()

        # Re-clasificar la condición basada en el promedio del tramo
        def get_cond(r):
            if r > 0.03: return 'Mala'
            if r > 0.01: return 'Regular'
            return 'Buena'
        aggregated['condicion_via'] = aggregated['roughness_score'].apply(get_cond)

        # Capas para diferentes servicios
        comercios_layer = folium.FeatureGroup(name="Detecciones IA (Comercios)")
        paradas_layer = folium.FeatureGroup(name="Detecciones IA (Paradas)")
        parques_layer = folium.FeatureGroup(name="Detecciones IA (Parques)")
        vias_layer = folium.FeatureGroup(name="Estado de Vías (Tramos 50m)")
        
        for idx, row in aggregated.iterrows():
            img_url = row.get('image_url', '')
            roughness = round(float(row.get('roughness_score', 0)), 4)
            
            # Helper para crear el HTML del popup
            def make_popup(title, img_url, extra_info=""):
                html = f'''
                <div style="width: 250px;">
                    <h4 style="margin-bottom:5px;">{title}</h4>
                    {extra_info}
                    <a href="{img_url}" target="_blank">
                        <img src="{img_url}" style="width:100%; border-radius:5px; cursor:pointer;" alt="{title}">
                    </a>
                </div>
                '''
                return folium.Popup(html, max_width=300)

            # Pintar la condición de la vía (Tramo Agrupado)
            cond = row['condicion_via']
            color_via = 'green' if cond == 'Buena' else ('orange' if cond == 'Regular' else 'red')
            folium.CircleMarker(
                location=[row['lat'], row['lon']],
                radius=14, # Un poco más grande para el tramo
                color=color_via,
                fill=True,
                fill_opacity=0.7,
                popup=make_popup(f"Tramo 50m: {cond}", img_url, f"<p>Rugosidad Promedio: {roughness}</p>")
            ).add_to(vias_layer)
            
            # Otros servicios (solo si se detectaron en el tramo)
            if row['comercio']:
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=5, color='blue', fill=True).add_to(comercios_layer)
            if row['parada_bus']:
                folium.Marker(location=[row['lat'], row['lon']], icon=folium.Icon(color='red', icon='info-sign')).add_to(paradas_layer)
            if row['parque_recreativo']:
                folium.CircleMarker(location=[row['lat'], row['lon']], radius=8, color='green', fill=True).add_to(parques_layer)
            
        comercios_layer.add_to(m)
        paradas_layer.add_to(m)
        parques_layer.add_to(m)
        vias_layer.add_to(m)
        folium.LayerControl().add_to(m)
        
    return m
        
    return m
