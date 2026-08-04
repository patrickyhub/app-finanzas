import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import plotly.graph_objects as go
import plotly.express as px

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Mis Finanzas", layout="wide")
st.title("🏦 Asesor Financiero (Sprint 4)")

# --- CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credenciales.json", scope)
    return gspread.authorize(creds)

def leer_hoja(nombre_hoja):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "MisFinanzas"  # <-- ¡CAMBIA por el nombre de tu archivo!
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        datos = hoja.get_all_records()
        return pd.DataFrame(datos)
    except gspread.WorksheetNotFound:
        st.warning(f"⚠️ La hoja '{nombre_hoja}' no existe. Créala en Google Sheets.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error leyendo '{nombre_hoja}': {e}")
        return pd.DataFrame()

def escribir_fila(nombre_hoja, fila_datos):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "MisFinanzas"
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        # Convertimos todo a string para evitar errores de tipo
        fila_str = [str(item) for item in fila_datos]
        hoja.append_row(fila_str)
        return True
    except Exception as e:
        st.error(f"Error al guardar en Sheets: {e}")
        return False

# --- LECTURA DE DATOS ---
df_transacciones = leer_hoja("Transacciones")
df_config = leer_hoja("Configuracion_Tarjeta")
df_palabras = leer_hoja("Palabras_Clave")

# --- 1. FUNCIÓN DE INTELIGENCIA (Clasificación) ---
def procesar_inteligencia(df, df_palabras):
    if df.empty:
        return df
    
    df_procesado = df.copy()
    
    # A. Clasificar gastos por palabras clave
    df_procesado['Clasificacion'] = 'Sin clasificar'
    if not df_palabras.empty:
        for idx, row in df_procesado.iterrows():
            desc = str(row.get('Descripcion', '')).lower()
            for _, p_row in df_palabras.iterrows():
                palabra = str(p_row.get('Palabra', '')).lower()
                if palabra and palabra in desc:
                    df_procesado.at[idx, 'Clasificacion'] = p_row.get('Clasificacion', 'Sin clasificar')
                    break
    
    # B. Detectar fijos (si aparece 3 veces con misma descripción y monto)
    df_procesado['Fijo_Detectado'] = 'No'
    if not df.empty and 'Descripcion' in df.columns and 'Monto' in df.columns:
        conteos = df_procesado.groupby(['Descripcion', 'Monto']).size().reset_index(name='Frecuencia')
        fijos = conteos[conteos['Frecuencia'] >= 3][['Descripcion', 'Monto']]
        for _, f_row in fijos.iterrows():
            mask = (df_procesado['Descripcion'] == f_row['Descripcion']) & (df_procesado['Monto'] == f_row['Monto'])
            df_procesado.loc[mask, 'Fijo_Detectado'] = 'Sí (Auto)'
    
    return df_procesado

df_procesado = procesar_inteligencia(df_transacciones, df_palabras)

# --- 2. DASHBOARD DE TARJETAS (Crédito + Débito) ---
st.subheader("💳 Estado de tus cuentas")

if not df_config.empty and not df_transacciones.empty:
    # Filtramos solo gastos
    df_gastos = df_transacciones[df_transacciones['Tipo'] == 'Gasto']
    
    # Creamos tantas columnas como tarjetas haya (máximo 4, se acomodan solas)
    num_tarjetas = len(df_config)
    cols = st.columns(min(num_tarjetas, 4))  # Máximo 4 columnas para no saturar
    
    for i, (idx, row) in enumerate(df_config.iterrows()):
        nombre = row.get('Tarjeta', 'Sin nombre')
        tipo = row.get('Tipo', 'Credito')  # Por defecto crédito
        limite = float(row.get('Limite_Credito', 0))
        fecha_pago = row.get('Fecha_Pago', '--')
        
        # Calcular movimientos de ESTA tarjeta
        df_cuenta = df_transacciones[df_transacciones['Tarjeta'] == nombre]
        total_ingresos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Ingreso']['Monto'].sum()
        total_gastos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Gasto']['Monto'].sum()
        saldo_disponible = total_ingresos_cuenta - total_gastos_cuenta
        
        with cols[i % 4]:  # Si hay más de 4, se envuelve
            st.markdown(f"### 🏦 {nombre}")
            
            if tipo == 'Credito' and limite > 0:
                # ----- TARJETA DE CRÉDITO (Medidor) -----
                total_gastado = total_gastos_cuenta
                porcentaje_uso = (total_gastado / limite) * 100 if limite > 0 else 0
                
                fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=total_gastado,
                    title={'text': f"{porcentaje_uso:.1f}% usado"},
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
                fig.update_layout(height=180, margin=dict(l=10, r=10, t=30, b=10))
                st.plotly_chart(fig, use_container_width=True)
                
                # Alertas de crédito
                if porcentaje_uso > 90:
                    st.error(f"🚨 Paga YA antes del día {fecha_pago}!")
                elif porcentaje_uso > 70:
                    st.warning(f"⚠️ Cerca del tope. Paga antes del {fecha_pago}.")
                else:
                    st.success(f"✅ Pago sugerido: día {fecha_pago}")
            
            else:
                # ----- TARJETA DE DÉBITO (Saldo disponible) -----
                st.metric(label="💰 Saldo disponible", value=f"S/ {saldo_disponible:,.2f}")
                if saldo_disponible < 0:
                    st.error("⚠️ ¡Estás en números rojos! Reduce tus gastos.")
                else:
                    st.info("💡 Recuerda que este es tu dinero real (no crédito).")

# --- 3. ASESOR FINANCIERO (Estrategias) ---
st.divider()
st.subheader("📊 Análisis y recomendaciones")

if not df_procesado.empty:
    df_gastos_proc = df_procesado[df_procesado['Tipo'] == 'Gasto']
    total_ingresos = df_procesado[df_procesado['Tipo'] == 'Ingreso']['Monto'].sum()
    total_gastos = df_gastos_proc['Monto'].sum()
    
    if total_ingresos > 0 and not df_gastos_proc.empty:
        # Clasificación para gráfico
        gastos_impulsivos = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Impulsivo']['Monto'].sum()
        gastos_necesarios = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Necesario']['Monto'].sum()
        sin_clasificar = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Sin clasificar']['Monto'].sum()
        
        col1, col2 = st.columns([1, 1])
        with col1:
            fig = px.pie(
                values=[gastos_impulsivos, gastos_necesarios, sin_clasificar],
                names=['Impulsivo', 'Necesario', 'Sin clasificar'],
                title='Distribución de gastos',
                color_discrete_map={'Impulsivo':'red', 'Necesario':'green', 'Sin clasificar':'gray'}
            )
            st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.markdown("### 💡 Estrategias personalizadas")
            # Impulsos
            pct_imp = (gastos_impulsivos / total_ingresos) * 100
            if gastos_impulsivos > 0:
                st.warning(f"💸 Gastaste S/ {gastos_impulsivos:,.2f} en impulsos ({pct_imp:.1f}% de ingresos).")
                if pct_imp > 15:
                    st.markdown("📉 **Consejo:** Aplica la regla de 30 días para compras no esenciales.")
                else:
                    st.markdown("👍 Vas bien en control de impulsos.")
            else:
                st.success("🎉 Sin gastos impulsivos, excelente!")
            
            # Fijos
            fijos = df_procesado[df_procesado['Fijo_Detectado'] == 'Sí (Auto)']
            if not fijos.empty:
                st.info(f"📌 Detecté {len(fijos)} gastos fijos (ej: {fijos['Descripcion'].iloc[0]}). Revisa si los necesitas.")
            
            # Ahorro
            st.success(f"💰 Meta de ahorro sugerida: 10% de ingresos = S/ {total_ingresos * 0.1:,.2f}")

# --- 4. FORMULARIO (A PRUEBA DE ERRORES) ---
st.divider()
st.subheader("✏️ Registrar nuevo movimiento")

with st.form("form_registro"):
    fecha = st.date_input("Fecha", datetime.now())
    descripcion = st.text_input("Descripción * (Obligatorio)", placeholder="Ej: Compra en Zara, Pago de luz")
    categoria = st.text_input("Categoría (Opcional)", placeholder="Ej: Ropa, Servicios")
    monto = st.number_input("Monto (S/)", min_value=0.01, step=0.5, format="%.2f")
    tipo = st.selectbox("Tipo", ["Gasto", "Ingreso"])
    
    # Opciones de tarjeta: obtenemos los nombres de la hoja de configuración
    opciones_tarjetas = ["No aplica"]
    if not df_config.empty and 'Tarjeta' in df_config.columns:
        opciones_tarjetas.extend(df_config['Tarjeta'].tolist())
    
    tarjeta = st.selectbox("Tarjeta/Cuenta asociada", opciones_tarjetas)
    es_fijo = st.checkbox("¿Es un gasto fijo mensual? (Ej: Netflix, Internet)")
    
    submitted = st.form_submit_button("Guardar movimiento")
    
    if submitted:
        # --- VALIDACIONES FUERTES (Evita errores) ---
        error = False
        if not descripcion.strip():
            st.error("❌ La 'Descripción' es obligatoria. Por favor, escríbela.")
            error = True
        if monto <= 0:
            st.error("❌ El 'Monto' debe ser mayor a 0.")
            error = True
        
        if not error:
            # Si no puso categoría, ponemos "Sin categoría"
            categoria_final = categoria.strip() if categoria.strip() else "Sin categoría"
            
            nueva_fila = [
                fecha.strftime("%d/%m/%Y"),
                descripcion.strip(),
                categoria_final,
                monto,
                tipo,
                tarjeta,
                "Sí" if es_fijo else "No"
            ]
            
            if escribir_fila("Transacciones", nueva_fila):
                st.success("✅ Movimiento guardado correctamente en la nube")
                st.balloons()
                st.rerun()

# --- 5. TABLA CON CLASIFICACIÓN ---
st.divider()
st.subheader("📋 Historial completo")

if not df_procesado.empty:
    # Mostramos columnas útiles, verificando que existan para no crashear
    columnas_mostrar = ['Fecha', 'Descripcion', 'Categoria', 'Monto', 'Tipo', 'Tarjeta', 'Clasificacion', 'Fijo_Detectado']
    columnas_existentes = [col for col in columnas_mostrar if col in df_procesado.columns]
    st.dataframe(df_procesado[columnas_existentes], use_container_width=True)
    
    # Mostramos el total de registros
    st.caption(f"Total de movimientos registrados: {len(df_procesado)}")
else:
    st.info("Aún no hay transacciones. ¡Agrega tu primer gasto o ingreso!")