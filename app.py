import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Mis Finanzas", layout="wide")
st.title("🧠 Mi Asesor Financiero Inteligente")

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    return gspread.authorize(creds)

def leer_hoja(nombre_hoja):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "app_mis_finanzas"  # <-- ¡CAMBIA por el nombre de tu archivo!
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        datos = hoja.get_all_records()
        return pd.DataFrame(datos)
    except Exception as e:
        st.error(f"Error leyendo '{nombre_hoja}': {e}")
        return pd.DataFrame()

def escribir_fila(nombre_hoja, fila_datos):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "app_mis_finanzas"
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        hoja.append_row(fila_datos)
        return True
    except Exception as e:
        st.error(f"Error al guardar: {e}")
        return False

# --- LECTURA DE TODAS LAS HOJAS ---
df_transacciones = leer_hoja("Transacciones")
df_config = leer_hoja("Configuracion_Tarjeta")
df_palabras = leer_hoja("Palabras_Clave")

# --- 1. INTELIGENCIA: CLASIFICACIÓN Y DETECCIÓN DE FIJOS ---
def procesar_inteligencia(df, df_palabras):
    if df.empty or df_palabras.empty:
        return df
    
    df_procesado = df.copy()
    
    # A. Clasificar como Impulsivo o Necesario (busca palabras clave)
    df_procesado['Clasificacion_Automatica'] = 'Sin clasificar'
    
    for idx, row in df_procesado.iterrows():
        desc = str(row['Descripcion']).lower()
        for _, p_row in df_palabras.iterrows():
            palabra = str(p_row['Palabra']).lower()
            if palabra in desc:
                df_procesado.at[idx, 'Clasificacion_Automatica'] = p_row['Clasificacion']
                break  # Si encuentra una, sale del bucle
    
    # B. Detectar gastos fijos automáticamente (si aparece 3 veces con mismo monto y descripción)
    # Agrupamos por descripción y monto, contamos cuántas veces aparece
    conteos = df_procesado.groupby(['Descripcion', 'Monto']).size().reset_index(name='Frecuencia')
    # Filtramos los que aparecen 3 o más veces
    fijos_detectados = conteos[conteos['Frecuencia'] >= 3][['Descripcion', 'Monto']]
    
    # Marcamos en el DataFrame principal
    df_procesado['Fijo_Automatico'] = 'No'
    for _, f_row in fijos_detectados.iterrows():
        mask = (df_procesado['Descripcion'] == f_row['Descripcion']) & (df_procesado['Monto'] == f_row['Monto'])
        df_procesado.loc[mask, 'Fijo_Automatico'] = 'Sí (Auto)'
    
    return df_procesado

# Procesamos los datos
df_procesado = procesar_inteligencia(df_transacciones, df_palabras)

# --- 2. DASHBOARD DE TARJETAS (Sprint 2 mejorado) ---
st.subheader("💳 Estado de tus Tarjetas")

if not df_transacciones.empty and not df_config.empty:
    df_gastos = df_transacciones[df_transacciones['Tipo'] == 'Gasto']
    
    col1, col2 = st.columns(2)
    
    for idx, row in df_config.iterrows():
        tarjeta_nombre = row['Tarjeta']
        limite = float(row['Limite_Credito'])
        fecha_pago = int(row['Fecha_Pago'])
        
        total_gastado = df_gastos[df_gastos['Tarjeta'] == tarjeta_nombre]['Monto'].sum()
        porcentaje_uso = (total_gastado / limite) * 100
        
        col_actual = col1 if idx == 0 else col2
        with col_actual:
            st.markdown(f"### 🏦 {tarjeta_nombre}")
            fig = go.Figure(go.Indicator(
                mode="gauge+number",
                value=total_gastado,
                title={'text': f"{porcentaje_uso:.1f}%"},
                domain={'x': [0, 1], 'y': [0, 1]},
                gauge={
                    'axis': {'range': [None, limite], 'tickprefix': 'S/'},
                    'bar': {'color': "darkblue"},
                    'steps': [
                        {'range': [0, limite*0.7], 'color': "lightgreen"},
                        {'range': [limite*0.7, limite*0.9], 'color': "yellow"},
                        {'range': [limite*0.9, limite], 'color': "salmon"}
                    ],
                    'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': limite}
                }
            ))
            fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=20))
            st.plotly_chart(fig, use_container_width=True)
            
            if porcentaje_uso > 90:
                st.error(f"🚨 ¡URGENTE! Paga antes del día {fecha_pago} para no generar intereses.")
            elif porcentaje_uso > 70:
                st.warning(f"⚠️ Cuidado, estás cerca del tope. Considera pagar antes del {fecha_pago}.")
            else:
                st.success(f"✅ Todo en orden. Fecha de pago: día {fecha_pago}")

# --- 3. ASESOR FINANCIERO (¡LA NOVEDAD DEL SPRINT 3!) ---
st.divider()
st.subheader("📈 Análisis Inteligente y Estrategias")

if not df_procesado.empty:
    # Filtramos solo gastos para el análisis
    df_gastos_proc = df_procesado[df_procesado['Tipo'] == 'Gasto']
    total_ingresos = df_procesado[df_procesado['Tipo'] == 'Ingreso']['Monto'].sum()
    total_gastos = df_gastos_proc['Monto'].sum()
    
    if total_ingresos > 0 and not df_gastos_proc.empty:
        # Calcular total de impulsivo vs necesario
        gastos_impulsivos = df_gastos_proc[df_gastos_proc['Clasificacion_Automatica'] == 'Impulsivo']['Monto'].sum()
        gastos_necesarios = df_gastos_proc[df_gastos_proc['Clasificacion_Automatica'] == 'Necesario']['Monto'].sum()
        sin_clasificar = df_gastos_proc[df_gastos_proc['Clasificacion_Automatica'] == 'Sin clasificar']['Monto'].sum()
        
        # Gráfico de torta (Dashboard visual)
        col_graf, col_texto = st.columns([1, 1])
        
        with col_graf:
            fig_pie = px.pie(
                values=[gastos_impulsivos, gastos_necesarios, sin_clasificar],
                names=['Impulsivo', 'Necesario', 'Sin clasificar'],
                title='Distribución de tus gastos',
                color_discrete_map={'Impulsivo':'red', 'Necesario':'green', 'Sin clasificar':'gray'}
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        
        with col_texto:
            st.markdown("### 🧾 Estrategias personalizadas")
            
            # Estrategia 1: Impulsos
            porcentaje_impulsos = (gastos_impulsivos / total_ingresos) * 100
            if gastos_impulsivos > 0:
                st.warning(f"💸 Gastaste **S/ {gastos_impulsivos:,.2f}** en compras impulsivas ({porcentaje_impulsos:.1f}% de tus ingresos).")
                if porcentaje_impulsos > 15:
                    st.markdown("📉 **Consejo:** Estás gastando más del 15% de tu sueldo en antojos. Prueba la regla de los *30 días*: espera un mes antes de comprar algo que no necesites.")
                else:
                    st.markdown("👍 **Consejo:** Vas bien en control de impulsos. Sigue así, pero intenta ahorrar ese monto para un fondo de emergencia.")
            else:
                st.success("🎉 ¡No tienes gastos impulsivos! Excelente disciplina financiera.")
            
            # Estrategia 2: Gastos Fijos detectados
            st.divider()
            fijos_detectados = df_procesado[df_procesado['Fijo_Automatico'] == 'Sí (Auto)']
            if not fijos_detectados.empty:
                st.info(f"📌 **Detecté {len(fijos_detectados)} gastos fijos** (se repiten 3 veces o más). Ejemplo: {fijos_detectados['Descripcion'].iloc[0]}")
                st.markdown("💡 Revisa si realmente usas todos estos servicios. Cancelar uno te ahorraría S/ 500 al año.")
            else:
                st.info("🔍 Aún no detecto gastos fijos. Sigue registrando tus gastos para que la app aprenda.")
            
            # Estrategia 3: Ahorro sugerido
            st.divider()
            ahorro_sugerido = total_ingresos * 0.1  # Sugerencia: ahorrar 10%
            st.success(f"💰 **Meta de ahorro sugerida:** S/ {ahorro_sugerido:,.2f} (10% de tus ingresos).")
            
            if total_gastos > total_ingresos:
                st.error("🚨 Estás gastando más de lo que ganas. Prioriza pagar tus tarjetas y reduce los gastos impulsivos al 0%.")
    else:
        st.info("Agrega ingresos para ver las estrategias financieras.")
else:
    st.warning("Agrega transacciones para ver el análisis.")

# --- 4. FORMULARIO PARA AGREGAR GASTOS ---
st.divider()
st.subheader("✏️ Registrar nuevo movimiento")

with st.form("form_registro"):
    fecha = st.date_input("Fecha", datetime.now())
    descripcion = st.text_input("Descripción (ej: Compra en Zara)")
    categoria = st.text_input("Categoría (ej: Ropa, Comida)")
    monto = st.number_input("Monto (S/)", min_value=0.01, step=0.5)
    tipo = st.selectbox("Tipo", ["Gasto", "Ingreso"])
    tarjeta = st.selectbox("Tarjeta (si es gasto)", ["Visa", "Mastercard", "No aplica"])
    es_fijo = st.checkbox("¿Es un gasto fijo? (Ej: Netflix)")
    
    submitted = st.form_submit_button("Guardar movimiento")
    if submitted:
        nueva_fila = [
            fecha.strftime("%d/%m/%Y"),
            descripcion,
            categoria,
            monto,
            tipo,
            tarjeta,
            "Sí" if es_fijo else "No"
        ]
        if escribir_fila("Transacciones", nueva_fila):
            st.success("✅ Guardado correctamente")
            st.balloons()
            st.rerun()  # Recarga para actualizar gráficos

# --- 5. TABLA CON CLASIFICACIÓN ---
st.divider()
st.subheader("📋 Historial con clasificación automática")
if not df_procesado.empty:
    # Mostramos columnas útiles
    mostrar_columnas = ['Fecha', 'Descripcion', 'Categoria', 'Monto', 'Tipo', 'Tarjeta', 'Clasificacion_Automatica', 'Fijo_Automatico']
    # Filtramos las que existen
    columnas_existentes = [col for col in mostrar_columnas if col in df_procesado.columns]
    st.dataframe(df_procesado[columnas_existentes], use_container_width=True)