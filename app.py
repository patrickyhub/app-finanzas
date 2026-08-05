import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import plotly.express as px
import plotly.graph_objects as go
import calendar

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Mis Finanzas", layout="wide")
st.title("🏦 Asesor Financiero (Sprint 4)")

# --- CONEXIÓN A GOOGLE SHEETS (CON CACHÉ) ---
@st.cache_resource
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS_JSON"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    except Exception:
        creds = Credentials.from_service_account_file("credenciales.json", scopes=scope)
    return gspread.authorize(creds)

def convertir_a_float(valor):
    if pd.isna(valor) or str(valor).strip() == '':
        return 0.0
    texto_limpio = str(valor).replace("S/", "").replace("s/", "").replace(",", "").strip()
    try:
        return float(texto_limpio)
    except (ValueError, TypeError):
        return 0.0

@st.cache_data(ttl=60)
def leer_hoja(nombre_hoja):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "app_mis_finanzas"
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        datos = hoja.get_all_records()
        df = pd.DataFrame(datos)
        
        if not df.empty:
            # 1. NUEVO: Limpiar espacios invisibles y capitalizar columnas de texto clave
            columnas_texto = ['Tipo', 'Tarjeta', 'Categoria']
            for col in columnas_texto:
                if col in df.columns:
                    # Convierte a texto, elimina espacios extra al inicio/final y pone Mayúscula Inicial (Ej: " ingreso " -> "Ingreso")
                    df[col] = df[col].astype(str).str.strip().str.title()
            
            # 2. Normalización preventiva de montos
            if 'Monto' in df.columns:
                df['Monto'] = df['Monto'].apply(convertir_a_float)
            if 'Comision' in df.columns:
                df['Comision'] = df['Comision'].apply(convertir_a_float)
                
        return df
    except gspread.WorksheetNotFound:
        st.warning(f"⚠️ La hoja '{nombre_hoja}' no existe. Créala en Google Sheets.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error leyendo '{nombre_hoja}': {e}")
        return pd.DataFrame()

def escribir_fila(nombre_hoja, fila_datos):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "app_mis_finanzas"
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
        fila_str = [str(item) for item in fila_datos]
        hoja.append_row(fila_str)
        st.cache_data.clear()  # Limpiar caché tras escritura exitosa
        return True
    except Exception as e:
        st.error(f"Error al guardar en Sheets: {e}")
        return False

# --- CARGA DE DATOS ---
df_transacciones = leer_hoja("Transacciones")
df_config = leer_hoja("Configuracion_Tarjeta")
df_palabras = leer_hoja("Palabras_Clave")

# --- LÓGICA INTELIGENTE ---
def procesar_inteligencia(df, df_palabras):
    if df.empty:
        return df
    df_procesado = df.copy()

    df_procesado['Clasificacion'] = 'Sin clasificar'
    if not df_palabras.empty:
        for idx, row in df_procesado.iterrows():
            desc = str(row.get('Descripcion', '')).lower()
            for _, p_row in df_palabras.iterrows():
                palabra = str(p_row.get('Palabra', '')).lower()
                if palabra and palabra in desc:
                    df_procesado.at[idx, 'Clasificacion'] = p_row.get('Clasificacion', 'Sin clasificar')
                    break

    df_procesado['Fijo_Detectado'] = 'No'
    if 'Descripcion' in df_procesado.columns and 'Monto' in df_procesado.columns:
        conteos = df_procesado.groupby(['Descripcion', 'Monto']).size().reset_index(name='Frecuencia')
        fijos = conteos[conteos['Frecuencia'] >= 3]
        for _, f_row in fijos.iterrows():
            mask = (df_procesado['Descripcion'] == f_row['Descripcion']) & (df_procesado['Monto'] == f_row['Monto'])
            df_procesado.loc[mask, 'Fijo_Detectado'] = 'Sí (Auto)'

    return df_procesado

df_procesado = procesar_inteligencia(df_transacciones, df_palabras)

# --- CÁLCULO DE CICLOS DE FACTURACIÓN (MEJORADO CON FECHAS DE PAGO) ---
hoy = date.today()

def dia_seguro(year, month, day):
    try:
        day = int(day)
    except (ValueError, TypeError):
        day = 15
    day = max(1, day)
    _, max_day = calendar.monthrange(year, month)
    return min(day, max_day)

def calcular_ciclo_tarjeta(row_config):
    try:
        dia_corte = int(row_config.get('Dia_Corte', 15))
        dia_pago = int(row_config.get('Dia_Pago', 5))
    except (ValueError, TypeError):
        dia_corte, dia_pago = 15, 5

    # 1. Calcular fechas de corte
    dc = dia_seguro(hoy.year, hoy.month, dia_corte)
    corte_actual = date(hoy.year, hoy.month, dc)

    if hoy < corte_actual:
        mes_ant = 12 if hoy.month == 1 else hoy.month - 1
        anio_ant = hoy.year - 1 if hoy.month == 1 else hoy.year
        ult_dc = dia_seguro(anio_ant, mes_ant, dia_corte)
        ultimo_corte = date(anio_ant, mes_ant, ult_dc)
        proximo_corte = corte_actual
    else:
        ultimo_corte = corte_actual
        mes_prox = 1 if hoy.month == 12 else hoy.month + 1
        anio_prox = hoy.year + 1 if hoy.month == 12 else hoy.year
        prox_dc = dia_seguro(anio_prox, mes_prox, dia_corte)
        proximo_corte = date(anio_prox, mes_prox, prox_dc)

    # 2. Calcular fecha de pago exacta para el ciclo que cierra en 'proximo_corte'
    # Normalmente, si el corte es un mes, se paga el mes siguiente.
    mes_pago_exacto = proximo_corte.month + 1
    anio_pago_exacto = proximo_corte.year
    if mes_pago_exacto > 12:
        mes_pago_exacto = 1
        anio_pago_exacto += 1
        
    dp = dia_seguro(anio_pago_exacto, mes_pago_exacto, dia_pago)
    fecha_pago_ciclo = date(anio_pago_exacto, mes_pago_exacto, dp)

    return ultimo_corte, proximo_corte, fecha_pago_ciclo

# --- DASHBOARD DE CUENTAS (CON GRÁFICOS PLOTLY) ---
st.subheader("💳 Estado de tus cuentas")

if not df_config.empty and not df_transacciones.empty:
    cols = st.columns(min(len(df_config), 4))

    for i, (_, row) in enumerate(df_config.iterrows()):
        nombre = str(row.get('Tarjeta', 'Sin nombre'))
        tipo = str(row.get('Tipo', 'Credito'))
        limite = convertir_a_float(row.get('Limite_Credito', 0))

        ultimo_corte, proximo_corte, fecha_pago_ciclo = calcular_ciclo_tarjeta(row)

        df_cuenta = df_transacciones[df_transacciones['Tarjeta'] == nombre]
        df_gastos = df_cuenta[df_cuenta['Tipo'] == 'Gasto'].copy()
        df_ingresos = df_cuenta[df_cuenta['Tipo'] == 'Ingreso']

        if not df_gastos.empty and 'Fecha' in df_gastos.columns:
            df_gastos['Fecha_Obj'] = pd.to_datetime(df_gastos['Fecha'], format='%d/%m/%Y', errors='coerce')
        else:
            df_gastos['Fecha_Obj'] = pd.NaT

        # Cálculo por ciclos
        mask_ciclo_actual = (df_gastos['Fecha_Obj'].dt.date >= ultimo_corte) & (df_gastos['Fecha_Obj'].dt.date < proximo_corte)
        total_a_pagar = df_gastos.loc[mask_ciclo_actual, 'Monto'].sum()

        mask_proximo_ciclo = (df_gastos['Fecha_Obj'].dt.date >= proximo_corte)
        total_proximo_ciclo = df_gastos.loc[mask_proximo_ciclo, 'Monto'].sum()

        total_ingresos = df_ingresos['Monto'].sum() if not df_ingresos.empty else 0.0
        total_gastos = df_gastos['Monto'].sum() if not df_gastos.empty else 0.0
        total_comisiones = df_gastos['Comision'].sum() if not df_gastos.empty and 'Comision' in df_gastos.columns else 0.0

        if tipo == 'Debito':
            saldo_disponible = total_ingresos - total_gastos
        else:
            saldo_disponible = limite - total_gastos - total_comisiones

        with cols[i % 4]:
            st.markdown(f"### 🏦 {nombre}")
            if tipo == 'Credito':
                # Gráfico Gauge con Plotly
                uso_total = total_gastos + total_comisiones
                pct_uso_total = (uso_total / limite * 100) if limite > 0 else 0
                
                # Definir color del gauge según porcentaje de uso
                color_barra = "#FF4B4B" if pct_uso_total >= 80 else "#FDE74C" if pct_uso_total >= 50 else "#1DD3B0"
                
                fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=uso_total,
                    number={'prefix': "S/ ", 'valueformat': ",.2f"},
                    domain={'x': [0, 1], 'y': [0, 1]},
                    gauge={
                        'axis': {'range': [0, limite], 'tickwidth': 1, 'tickcolor': "darkblue"},
                        'bar': {'color': color_barra},
                        'bgcolor': "white",
                        'borderwidth': 2,
                        'bordercolor': "gray",
                        'steps': [
                            {'range': [0, limite * 0.5], 'color': "rgba(29, 211, 176, 0.15)"},
                            {'range': [limite * 0.5, limite * 0.8], 'color': "rgba(253, 231, 76, 0.15)"},
                            {'range': [limite * 0.8, limite], 'color': "rgba(255, 75, 75, 0.15)"}
                        ],
                        'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': limite}
                    }
                ))
                fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=20))
                st.plotly_chart(fig, use_container_width=True)

                st.metric(label="💰 Deuda del ciclo actual", value=f"S/ {total_a_pagar:,.2f}")
                
                # Fechas dinámicas del ciclo
                st.info(f"**Corte:** {proximo_corte.strftime('%d %b')} | **Pago:** {fecha_pago_ciclo.strftime('%d %b')}")
                
                if total_proximo_ciclo > 0:
                    st.warning(f"🗓️ Gastos para el **próximo ciclo**: S/ {total_proximo_ciclo:,.2f}")

                st.caption(f"Saldo libre: S/ {saldo_disponible:,.2f}")
            else:
                st.metric(label="💰 Saldo disponible", value=f"S/ {saldo_disponible:,.2f}")
                if saldo_disponible < 0:
                    st.error("⚠️ En números rojos")

# --- ANÁLISIS FINANCIERO ---
st.divider()
st.subheader("📊 Análisis y recomendaciones")
if not df_procesado.empty:
    df_gastos_proc = df_procesado[df_procesado['Tipo'] == 'Gasto']
    total_ingresos = df_procesado[df_procesado['Tipo'] == 'Ingreso']['Monto'].sum()

    if total_ingresos > 0 and not df_gastos_proc.empty:
        gastos_impulsivos = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Impulsivo']['Monto'].sum()
        gastos_necesarios = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Necesario']['Monto'].sum()
        sin_clasificar = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Sin clasificar']['Monto'].sum()

        col1, col2 = st.columns([1, 1])
        with col1:
            fig = px.pie(
                values=[gastos_impulsivos, gastos_necesarios, sin_clasificar],
                names=['Impulsivo', 'Necesario', 'Sin clasificar'],
                title='Distribución de gastos',
                color_discrete_map={'Impulsivo':'#FF6B6B', 'Necesario':'#51CF66', 'Sin clasificar':'#ADB5BD'}
            )
            fig.update_traces(textposition='inside', textinfo='percent+label')
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.markdown("### 💡 Estrategias personalizadas")
            pct_imp = (gastos_impulsivos / total_ingresos) * 100
            if gastos_impulsivos > 0:
                st.warning(f"💸 Gastos impulsivos: S/ {gastos_impulsivos:,.2f} ({pct_imp:.1f}% de ingresos).")
            else: 
                st.success("🎉 Sin gastos impulsivos registrados.")

            st.success(f"💰 Meta de ahorro (10%): S/ {total_ingresos * 0.1:,.2f}")

# --- FORMULARIO DE REGISTRO ---
st.divider()
st.subheader("✍️ Registrar nuevo movimiento")

opciones_tarjetas = df_config['Tarjeta'].tolist() if not df_config.empty else ["Efectivo"]

with st.form("form_registro"):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        fecha = st.date_input("Fecha", value=date.today())
        descripcion = st.text_input("Descripción")
        tipo = st.selectbox("Tipo de movimiento", ["Gasto", "Ingreso"])
    
    with col_f2:
        monto = st.number_input("Monto (S/)", min_value=0.0, step=10.0)
        categoria = st.text_input("Categoría", value="General")
        tarjeta = st.selectbox("Cuenta / Tarjeta", opciones_tarjetas)

    with col_f3:
        es_fijo = st.checkbox("¿Es gasto fijo?")
        es_ruleteo = st.checkbox("¿Es operacion de Ruleteo?")
        comision_ruleteo = st.number_input("Comisión Ruleteo (S/)", min_value=0.0, step=1.0) if es_ruleteo else 0.0

    submitted = st.form_submit_button("Guardar movimiento")

if submitted:
    if not descripcion.strip():
        st.error("❌ La 'Descripción' es obligatoria.")
    elif monto <= 0:
        st.error("❌ El 'Monto' debe ser mayor a 0.")
    else:
        nueva_fila = [
            fecha.strftime("%d/%m/%Y"),
            descripcion.strip(),
            categoria.strip(),
            monto,
            tipo,
            tarjeta,
            "Sí" if es_fijo else "No",
            comision_ruleteo
        ]
        
        if es_ruleteo:
            cuenta_debito = "Cuenta_Sueldo"
            if not df_config.empty and 'Tipo' in df_config.columns:
                debitos = df_config[df_config['Tipo'] == 'Debito']['Tarjeta'].tolist()
                if debitos:
                    cuenta_debito = debitos[0]

            if escribir_fila("Transacciones", nueva_fila):
                fila_ingreso_ruleteo = [
                    fecha.strftime("%d/%m/%Y"),
                    f"INGRESO POR RULETEO: {descripcion.strip()}",
                    "Ingresos",
                    monto - comision_ruleteo,
                    "Ingreso",
                    cuenta_debito,
                    "No",
                    0.0
                ]
                escribir_fila("Transacciones", fila_ingreso_ruleteo)
                st.success("✅ Ruleteo guardado correctamente.")
                st.rerun()
        else:
            if escribir_fila("Transacciones", nueva_fila):
                st.success("✅ Movimiento guardado correctamente.")
                st.rerun()

# --- HISTORIAL ---
st.divider()
st.subheader("📋 Historial completo")
if not df_procesado.empty:
    cols_mostrar = ['Fecha', 'Descripcion', 'Categoria', 'Monto', 'Tipo', 'Tarjeta', 'Clasificacion', 'Fijo_Detectado', 'Comision']
    cols_existentes = [c for c in cols_mostrar if c in df_procesado.columns]
    st.dataframe(df_procesado[cols_existentes], use_container_width=True)
else:
    st.info("Aún no hay transacciones registradas.")