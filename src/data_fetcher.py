import osmnx as ox
import geopandas as gpd
import requests
import pandas as pd

def fetch_street_network(place_name):
    """
    Descarga la red vial de una comunidad usando OpenStreetMap.
    """
    try:
        # Descargar la red vial (calles y caminos)
        graph = ox.graph_from_place(place_name, network_type='drive')
        # Proyectar el grafo
        graph_proj = ox.project_graph(graph)
        # Convertir a GeoDataFrames
        nodes, edges = ox.graph_to_gdfs(graph_proj)
        
        # Volver a proyectar a WGS84 para mapas web (EPSG:4326)
        edges_wgs84 = edges.to_crs(epsg=4326)
        
        return edges_wgs84, None
    except Exception as e:
        return None, str(e)

def fetch_street_network_from_polygon(polygon):
    """
    Descarga la red vial dentro de un polígono irregular (Shapely Polygon).
    """
    try:
        # Descargar la red vial (calles y caminos) dentro del polígono
        graph = ox.graph_from_polygon(polygon, network_type='drive')
        # Proyectar el grafo
        graph_proj = ox.project_graph(graph)
        # Convertir a GeoDataFrames
        nodes, edges = ox.graph_to_gdfs(graph_proj)
        
        # Volver a proyectar a WGS84 para mapas web (EPSG:4326)
        edges_wgs84 = edges.to_crs(epsg=4326)
        
        return edges_wgs84, None
    except Exception as e:
        return None, f"No se encontró red vial en el área o error: {str(e)}"

def fetch_pois_from_polygon(polygon):
    """
    Descarga puntos de interés (comercios, servicios) usando OSMnx.
    """
    try:
        # Definir las etiquetas que nos interesan para "comercios" y "servicios"
        tags = {
            'shop': True, 
            'amenity': [
                'restaurant', 'cafe', 'pharmacy', 'bank', 'fuel', 
                'hospital', 'school', 'clinic', 'fire_station', 
                'university', 'college', 'kindergarten', 'doctors', 'atm'
            ],
            'leisure': 'park',
            'highway': 'bus_stop'
        }
        
        # Descargar características
        pois = ox.features_from_polygon(polygon, tags=tags)
        
        if pois.empty:
            return gpd.GeoDataFrame(), None
            
        # Asegurarnos de que sea WGS84
        pois = pois.to_crs(epsg=4326)
        
        # Simplificar: solo queremos puntos (si son polígonos, tomamos el centroide)
        pois['geometry'] = pois.geometry.centroid
        
        return pois, None
    except Exception as e:
        return gpd.GeoDataFrame(), str(e)

def generate_sample_points(edges_gdf, distance_meters=50):
    """
    Genera puntos de muestreo a lo largo de las calles cada N metros (interpolación real).
    """
    import numpy as np
    from shapely.geometry import Point
    
    # Proyectar a metros para interpolar correctamente
    edges_proj = edges_gdf.to_crs(epsg=3857)
    all_points = []
    
    for _, row in edges_proj.iterrows():
        geom = row.geometry
        length = geom.length
        # Crear puntos cada N metros
        distances = np.arange(0, length, distance_meters)
        for dist in distances:
            point = geom.interpolate(dist)
            # Crear un diccionario con la info de la calle
            p_data = row.to_dict()
            p_data['geometry'] = point
            all_points.append(p_data)
            
    points_gdf = gpd.GeoDataFrame(all_points, crs=edges_proj.crs)
    # Volver a WGS84
    return points_gdf.to_crs(epsg=4326)

def fetch_mapillary_images(bbox, client_id):
    """
    Descarga metadatos de imágenes de Mapillary. Retorna (GDF, error_msg).
    """
    url = "https://graph.mapillary.com/images"
    
    # Asegurar que el token tenga el formato correcto MLY|token
    token = client_id if client_id.startswith("MLY|") else f"MLY|{client_id}"
    
    params = {
        'access_token': token,
        'fields': 'id,geometry,thumb_256_url',
        'bbox': bbox,
        'limit': 500
    }
    
    if not client_id or "YOUR_CLIENT_ID" in client_id:
        return gpd.GeoDataFrame(), "No se proporcionó un token de Mapillary válido."

    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            features = data.get('data', [])
            
            if not features:
                return gpd.GeoDataFrame(), "No se encontraron fotos en esta zona exacta."
                
            df = pd.DataFrame(features)
            df['lon'] = df['geometry'].apply(lambda x: x['coordinates'][0])
            df['lat'] = df['geometry'].apply(lambda x: x['coordinates'][1])
            
            gdf = gpd.GeoDataFrame(
                df, 
                geometry=gpd.points_from_xy(df.lon, df.lat),
                crs="EPSG:4326"
            )
            return gdf, None
        elif response.status_code == 401 or response.status_code == 403:
            return gpd.GeoDataFrame(), f"Error de Autenticación (401/403): El token de Mapillary es inválido o ha expirado."
        else:
            return gpd.GeoDataFrame(), f"Error de Mapillary API ({response.status_code}): {response.text}"
    except Exception as e:
        return gpd.GeoDataFrame(), f"Error de conexión con Mapillary: {str(e)}"
