import cv2
import numpy as np
from ultralytics import YOLO
import requests
from io import BytesIO
from PIL import Image

# Diccionario de clases COCO que pueden mapearse a nuestros intereses
# 0: person, 2: car, 9: traffic light, 11: stop sign, 13: bench (parques/paradas)
# Para "comercios" y "condición de vías" se requeriría un modelo custom, 
# pero usamos el preentrenado como MVP.
RELEVANT_CLASSES = {
    9: 'semaforo',
    11: 'senal_alto',
    13: 'banca_recreativa',
    2: 'vehiculo',
    5: 'bus',
    56: 'silla',  # Proxy para comercios/cafés
    62: 'tv',     # Proxy para comercios
}

def load_model(model_name='yolo11x.pt'):
    """
    Carga el modelo YOLO preentrenado. 'yolo11x.pt' es el modelo Extra Large (máxima precisión).
    """
    try:
        model = YOLO(model_name)
        return model
    except Exception as e:
        print(f"Error cargando YOLO: {e}")
        return None

def analyze_road_texture(img_pil):
    """
    Analiza la textura de la calle usando OpenCV para detectar irregularidades.
    Retorna un score de rugosidad (0 a 1).
    """
    try:
        # Convertir PIL a OpenCV (BGR)
        open_cv_image = np.array(img_pil.convert('RGB'))
        img = open_cv_image[:, :, ::-1].copy() 
        
        # Tomar solo el tercio inferior (donde suele estar la calle)
        h, w, _ = img.shape
        roi = img[int(h*0.6):h, :, :]
        
        # Convertir a gris y aplicar filtro para resaltar texturas/grietas
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        
        # Detección de bordes (Canny) - grietas y baches generan bordes fuertes
        edges = cv2.Canny(blur, 50, 150)
        
        # Calcular densidad de bordes en la calle
        edge_density = np.sum(edges > 0) / (edges.shape[0] * edges.shape[1])
        
        return edge_density # Valores típicos: < 0.02 (Liso), > 0.05 (Rugoso/Dañado)
    except Exception as e:
        print(f"Error en análisis de textura: {e}")
        return 0

def analyze_image_url(model_gen, model_road, image_url):
    """
    Ejecuta inferencia dual: 
    1. model_gen (YOLO11x) para infraestructura.
    2. model_road (Custom) para baches/daños si existe.
    3. OpenCV para textura como respaldo.
    """
    try:
        response = requests.get(image_url)
        img_pil = Image.open(BytesIO(response.content))
        
        detections = {}
        
        # 1. Inferencia General (Comercios, paradas, etc)
        if model_gen:
            results_gen = model_gen(img_pil, verbose=False)
            for r in results_gen:
                for box in r.boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id in RELEVANT_CLASSES:
                        label = RELEVANT_CLASSES[cls_id]
                        detections[label] = detections.get(label, 0) + 1

        # 2. Inferencia de Vías (Baches/Grietas)
        if model_road:
            # Si el usuario provee un modelo especializado
            results_road = model_road(img_pil, verbose=False)
            has_damage = len(results_road[0].boxes) > 0
            detections['road_damage_detected'] = has_damage
        
        # 3. Respaldo OpenCV para textura
        detections['road_roughness'] = analyze_road_texture(img_pil)
        
        return detections
    except Exception as e:
        print(f"Error en inferencia dual: {e}")
        return {}

def mock_analyze_community(points_gdf):
    """
    Analiza la comunidad usando datos de OSM para la vía y simulación para el resto.
    """
    import random
    import pandas as pd
    
    results = []
    
    for idx, row in points_gdf.iterrows():
        # Lógica inteligente para condición de vía basada en OSM
        surface = str(row.get('surface', 'unknown')).lower()
        smoothness = str(row.get('smoothness', 'unknown')).lower()
        
        if surface in ['unpaved', 'gravel', 'dirt', 'earth', 'ground'] or smoothness in ['bad', 'very_bad', 'horrible']:
            condicion_via = 'Mala'
        elif smoothness == 'intermediate' or surface in ['cobblestone', 'sett']:
            condicion_via = 'Regular'
        else:
            condicion_via = 'Buena'

        # El resto sigue siendo simulado si no hay fotos
        tiene_comercio = random.random() > 0.8
        tiene_parada = random.random() > 0.9
        tiene_parque = random.random() > 0.95
        
        detections = {
            'comercio': tiene_comercio,
            'parada_bus': tiene_parada,
            'parque_recreativo': tiene_parque,
            'condicion_via': condicion_via,
            'lat': row.geometry.y,
            'lon': row.geometry.x,
            'image_url': f"https://images.unsplash.com/photo-1449824913935-59a10b8d2000?auto=format&fit=crop&w=400&q=80",
            'roughness_score': 0.05 if condicion_via == 'Mala' else (0.02 if condicion_via == 'Regular' else 0.005)
        }
        results.append(detections)
        
    return pd.DataFrame(results)

def analyze_real_mapillary_images(mapillary_gdf):
    """
    Carga ambos modelos y ejecuta el análisis integral.
    """
    import pandas as pd
    import streamlit as st
    import os
    
    # Cargar modelos
    model_gen = load_model('yolo11x.pt')
    
    # Intentar cargar un modelo especializado si existe en la carpeta
    road_model_path = 'pothole_model.pt'
    model_road = None
    if os.path.exists(road_model_path):
        model_road = load_model(road_model_path)
        st.sidebar.success("🚀 Modelo de baches detectado y activo.")
    else:
        st.sidebar.info("ℹ️ Usando análisis de textura OpenCV (no se encontró pothole_model.pt).")
        
    results = []
    if 'st' in globals():
        progress_bar = st.progress(0)
    else:
        progress_bar = None

    total_images = len(mapillary_gdf)
    
    for idx, row in mapillary_gdf.iterrows():
        img_url = row.get('thumb_256_url')
        detections = analyze_image_url(model_gen, model_road, img_url)
        
        # Lógica de decisión de estado
        roughness = detections.get('road_roughness', 0)
        damage_ai = detections.get('road_damage_detected', False)
        
        # Umbrales más realistas para evitar que todo salga como "Mala"
        if damage_ai or roughness > 0.08:
            condicion_via = 'Mala'
        elif roughness > 0.04:
            condicion_via = 'Regular'
        else:
            condicion_via = 'Buena'
            
        res = {
            'comercio': detections.get('silla', 0) > 0 or detections.get('tv', 0) > 0,
            'parada_bus': detections.get('bus', 0) > 0 or detections.get('banca_recreativa', 0) > 0,
            'parque_recreativo': detections.get('banca_recreativa', 0) > 1,
            'condicion_via': condicion_via,
            'lat': row.geometry.y,
            'lon': row.geometry.x,
            'image_url': img_url,
            'roughness_score': round(float(roughness), 4)
        }
        results.append(res)
        
        if progress_bar:
            progress_bar.progress(min((idx + 1) / total_images, 1.0))
            
    if progress_bar:
        progress_bar.empty()
        
    return pd.DataFrame(results)
