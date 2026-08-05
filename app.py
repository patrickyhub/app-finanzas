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

# 💡 NUEVO: BARRA LATERAL PARA TIPO DE CAMBIO
with st.sidebar:
    st.header("⚙️ Configuración")
    # Puedes cambiar el 3.75 por el tipo de cambio actual del día
    tipo_cambio = st.number_input("Tipo de Cambio (USD a S/)", value=3.75, step=0.01)
    st.info(f"Tus consumos en dólares se multiplicarán por {tipo_cambio} para calcular tu línea de crédito disponible y tus estadísticas.")

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
    texto_limpio = str(valor).replace("S/", "").replace("s/", "").replace("$", "").replace(",", "").strip()
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
            columnas_texto = ['Tipo', 'Tarjeta', 'Categoria']
            for col in columnas_texto:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.strip().str.title()
            
            if 'Moneda' not in df.columns:
                df['Moneda'] = 'PEN'
            df['Moneda'] = df['Moneda'].astype(str).str.strip().str.upper()
            df['Moneda'] = df['Moneda'].replace({'': 'PEN', 'SOLES': 'PEN', 'DOLARES': 'USD'})
            
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
        st.cache_data.clear()  
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
            
    # 💡 NUEVO: Creamos una columna invisible unificada en Soles para cálculos globales
    if 'Moneda' in df_procesado.columns and 'Monto' in df_procesado.columns:
        df_procesado['Monto_PEN'] = df_procesado.apply(
            lambda x: x['Monto'] * tipo_cambio if x['Moneda'] == 'USD' else x['Monto'], axis=1
        )

    return df_procesado

df_procesado = procesar_inteligencia(df_transacciones, df_palabras)

# --- CÁLCULO DE CICLOS DE FACTURACIÓN ---
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

    mes_pago_exacto = proximo_corte.month + 1
    anio_pago_exacto = proximo_corte.year
    if mes_pago_exacto > 12:
        mes_pago_exacto = 1
        anio_pago_exacto += 1
        
    dp = dia_seguro(anio_pago_exacto, mes_pago_exacto, dia_pago)
    fecha_pago_ciclo = date(anio_pago_exacto, mes_pago_exacto, dp)

    return ultimo_corte, proximo_corte, fecha_pago_ciclo

# --- DASHBOARD DE CUENTAS (MULTI-MONEDA INTEGRADO) ---
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

        df_gastos_pen = df_gastos[df_gastos['Moneda'] != 'USD']
        df_gastos_usd = df_gastos[df_gastos['Moneda'] == 'USD']

        mask_ciclo_actual = (df_gastos['Fecha_Obj'].dt.date >= ultimo_corte) & (df_gastos['Fecha_Obj'].dt.date < proximo_corte)
        mask_proximo_ciclo = (df_gastos['Fecha_Obj'].dt.date >= proximo_corte)

        # Cálculos en pantalla separados (S/ y $)
        total_a_pagar_pen = df_gastos_pen.loc[mask_ciclo_actual, 'Monto'].sum()
        total_proximo_ciclo_pen = df_gastos_pen.loc[mask_proximo_ciclo, 'Monto'].sum()
        
        total_a_pagar_usd = df_gastos_usd.loc[mask_ciclo_actual, 'Monto'].sum()
        total_proximo_ciclo_usd = df_gastos_usd.loc[mask_proximo_ciclo, 'Monto'].sum()

        # 💡 NUEVO: Cálculos globales (Todo llevado a Soles) para la línea de crédito
        total_gastos_pen = df_gastos_pen['Monto'].sum() if not df_gastos_pen.empty else 0.0
        total_gastos_usd = df_gastos_usd['Monto'].sum() if not df_gastos_usd.empty else 0.0
        total_comisiones_pen = df_gastos_pen['Comision'].sum() if not df_gastos_pen.empty and 'Comision' in df_gastos_pen.columns else 0.0
        
        # Consumo total unificado
        uso_total_consolidado = total_gastos_pen + total_comisiones_pen + (total_gastos_usd * tipo_cambio)

        if tipo == 'Debito':
            # Si es débito sumamos los ingresos unificados
            total_ingresos_pen = df_ingresos[df_ingresos['Moneda'] != 'USD']['Monto'].sum() if not df_ingresos.empty else 0.0
            total_ingresos_usd = df_ingresos[df_ingresos['Moneda'] == 'USD']['Monto'].sum() if not df_ingresos.empty else 0.0
            saldo_disponible = (total_ingresos_pen + (total_ingresos_usd * tipo_cambio)) - uso_total_consolidado
        else:
            # Si es crédito, restamos el consumo unificado al límite
            saldo_disponible = limite - uso_total_consolidado

        with cols[i % 4]:
            st.markdown(f"### 🏦 {nombre}")
            if tipo == 'Credito':
                pct_uso_total = (uso_total_consolidado / limite * 100) if limite > 0 else 0
                color_barra = "#FF4B4B" if pct_uso_total >= 80 else "#FDE74C" if pct_uso_total >= 50 else "#1DD3B0"
                
                # Gauge chart (Unificado en Soles)
                fig = go.Figure(go.Indicator(
                    mode="gauge+number",
                    value=uso_total_consolidado,
                    number={'prefix': "S/ ", 'valueformat': ",.2f"},
                    domain={'x': [0, 1], 'y': [0, 1]},
                    title={'text': "Uso Total (Eq. Soles)", 'font': {'size': 14}},
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
                fig.update_layout(height=200, margin=dict(l=20, r=20, t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)

                c1, c2 = st.columns(2)
                c1.metric(label="Deuda ciclo (S/)", value=f"S/ {total_a_pagar_pen:,.2f}")
                c2.metric(label="Deuda ciclo ($)", value=f"$ {total_a_pagar_usd:,.2f}")
                
                st.info(f"**Corte:** {proximo_corte.strftime('%d %b')} | **Pago:** {fecha_pago_ciclo.strftime('%d %b')}")
                
                if total_proximo_ciclo_pen > 0 or total_proximo_ciclo_usd > 0:
                    st.warning(f"🗓️ **Próximo ciclo:** S/ {total_proximo_ciclo_pen:,.2f} | $ {total_proximo_ciclo_usd:,.2f}")

                st.caption(f"Línea libre aprox.: S/ {saldo_disponible:,.2f}")
            else:
                st.metric(label="💰 Saldo aprox. (S/)", value=f"S/ {saldo_disponible:,.2f}")
                if saldo_disponible < 0:
                    st.error("⚠️ En números rojos")

# --- ANÁLISIS FINANCIERO UNIFICADO ---
st.divider()
st.subheader("📊 Análisis y recomendaciones globales")
if not df_procesado.empty:
    # 💡 NUEVO: Utilizamos Monto_PEN para que el gráfico sume tanto soles como dólares convertidos
    df_gastos_proc = df_procesado[df_procesado['Tipo'] == 'Gasto']
    total_ingresos = df_procesado[df_procesado['Tipo'] == 'Ingreso']['Monto_PEN'].sum()

    if total_ingresos > 0 and not df_gastos_proc.empty:
        gastos_impulsivos = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Impulsivo']['Monto_PEN'].sum()
        gastos_necesarios = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Necesario']['Monto_PEN'].sum()
        sin_clasificar = df_gastos_proc[df_gastos_proc['Clasificacion'] == 'Sin clasificar']['Monto_PEN'].sum()

        col1, col2 = st.columns([1, 1])
        with col1:
            fig = px.pie(
                values=[gastos_impulsivos, gastos_necesarios, sin_clasificar],
                names=['Impulsivo', 'Necesario', 'Sin clasificar'],
                title='Distribución de gastos (Soles + Dólares Eq.)',
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
es_ruleteo = st.checkbox("🔄 ¿Es una operación de Ruleteo?")

with st.form("form_registro"):
    col_f1, col_f2, col_f3 = st.columns(3)
    
    with col_f1:
        fecha = st.date_input("Fecha", value=date.today())
        descripcion = st.text_input("Descripción")
        tipo = st.selectbox("Tipo de movimiento", ["Gasto", "Ingreso"])
    
    with col_f2:
        col_m1, col_m2 = st.columns([2, 1])
        with col_m1:
            monto = st.number_input("Monto", min_value=0.0, step=10.0)
        with col_m2:
            moneda = st.selectbox("Moneda", ["PEN (S/)", "USD ($)"]) 
            
        categoria = st.text_input("Categoría", value="General")
        tarjeta = st.selectbox("Cuenta / Tarjeta", opciones_tarjetas)

    with col_f3:
        es_fijo = st.checkbox("¿Es gasto fijo?")
        if es_ruleteo:
            comision_ruleteo = st.number_input("💸 Comisión Ruleteo (S/)", min_value=0.0, step=1.0)
        else:
            comision_ruleteo = 0.0

    submitted = st.form_submit_button("Guardar movimiento")

if submitted:
    if not descripcion.strip():
        st.error("❌ La 'Descripción' es obligatoria.")
    elif monto <= 0:
        st.error("❌ El 'Monto' debe ser mayor a 0.")
    else:
        moneda_str = "USD" if "USD" in moneda else "PEN"
        
        nueva_fila = [
            fecha.strftime("%d/%m/%Y"),
            descripcion.strip(),
            categoria.strip(),
            monto,
            tipo,
            tarjeta,
            "Sí" if es_fijo else "No",
            comision_ruleteo,
            moneda_str
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
                    "Ingreso", 
                    monto - comision_ruleteo,
                    "Ingreso",
                    cuenta_debito,
                    "No",
                    0.0,
                    moneda_str 
                ]
                escribir_fila("Transacciones", fila_ingreso_ruleteo)
                st.success("✅ Ruleteo guardado correctamente.")
                st.rerun()
        else:
            if escribir_fila("Transacciones", nueva_fila):
                st.success("✅ Movimiento guardado correctamente.")
                st.rerun()

# --- HISTORIAL (CON FILTRO POR MES) ---
st.divider()
st.subheader("📋 Historial completo")
if not df_procesado.empty:
    
    fechas_validas = pd.to_datetime(df_procesado['Fecha'], format='%d/%m/%Y', errors='coerce')
    df_procesado['Mes_Filtro'] = fechas_validas.dt.strftime('%m/%Y').fillna('Desconocido')
    
    meses_disponibles = ['Todos'] + sorted(
        df_procesado[df_procesado['Mes_Filtro'] != 'Desconocido']['Mes_Filtro'].unique().tolist(), 
        reverse=True
    )
    
    filtro_mes = st.selectbox("📅 Filtrar por mes:", meses_disponibles)
    
    df_mostrar = df_procesado.copy()
    if filtro_mes != 'Todos':
        df_mostrar = df_mostrar[df_mostrar['Mes_Filtro'] == filtro_mes]
        
    cols_mostrar = ['Fecha', 'Descripcion', 'Categoria', 'Monto', 'Moneda', 'Tipo', 'Tarjeta', 'Clasificacion', 'Comision']
    cols_existentes = [c for c in cols_mostrar if c in df_mostrar.columns]
    
    st.dataframe(df_mostrar[cols_existentes], use_container_width=True)
    st.caption(f"Mostrando {len(df_mostrar)} movimientos para: {filtro_mes}")
else:
    st.info("Aún no hay transacciones registradas.")