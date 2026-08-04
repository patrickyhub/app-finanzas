import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.express as px
import json
import calendar

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="Mis Finanzas", layout="wide")
st.title("🏦 Asesor Financiero (Sprint 4)")

# --- CONEXIÓN A GOOGLE SHEETS ---
def conectar_google_sheets():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        creds_dict = dict(st.secrets["GOOGLE_CREDENTIALS_JSON"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    except Exception:
        creds = Credentials.from_service_account_file("credenciales.json", scopes=scope)
    return gspread.authorize(creds)

def leer_hoja(nombre_hoja):
    cliente = conectar_google_sheets()
    NOMBRE_ARCHIVO = "app_mis_finanzas"
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
    NOMBRE_ARCHIVO = "app_mis_finanzas"
    try:
        libro = cliente.open(NOMBRE_ARCHIVO)
        hoja = libro.worksheet(nombre_hoja)
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

# --- PROCESAMIENTO DE INTELIGENCIA ---
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

    # B. Detectar fijos
    df_procesado['Fijo_Detectado'] = 'No'
    if not df.empty and 'Descripcion' in df.columns and 'Monto' in df.columns:
        conteos = df_procesado.groupby(['Descripcion', 'Monto']).size().reset_index(name='Frecuencia')
        fijos = conteos[conteos['Frecuencia'] >= 3][['Descripcion', 'Monto']]
        for _, f_row in fijos.iterrows():
            mask = (df_procesado['Descripcion'] == f_row['Descripcion']) & (df_procesado['Monto'] == f_row['Monto'])
            df_procesado.loc[mask, 'Fijo_Detectado'] = 'Sí (Auto)'

    return df_procesado

df_procesado = procesar_inteligencia(df_transacciones, df_palabras)

# --- LÓGICA DE CICLO DE FACTURACIÓN (ULTRA-DEFENSIVA) ---
hoy = date.today()

def dia_seguro(year, month, day):
    """Devuelve un día válido para el mes/año dado."""
    try:
        day = int(day)
    except (ValueError, TypeError):
        day = 15
    if day < 1:
        day = 1
    _, max_day = calendar.monthrange(year, month)
    if day > max_day:
        day = max_day
    return day

def calcular_ciclo_tarjeta(row_config):
    try:
        dia_corte_raw = row_config.get('Dia_Corte', 15)
        dia_pago_raw = row_config.get('Dia_Pago', 5)
        dia_corte = int(dia_corte_raw) if str(dia_corte_raw).strip() != '' else 15
        dia_pago = int(dia_pago_raw) if str(dia_pago_raw).strip() != '' else 5
    except Exception:
        dia_corte = 15
        dia_pago = 5

    # Fecha de corte del mes actual (ajustada)
    dc = dia_seguro(hoy.year, hoy.month, dia_corte)
    corte_actual = date(hoy.year, hoy.month, dc)

    if hoy < corte_actual:
        # Último corte fue el mes pasado
        if hoy.month == 1:
            ult_dc = dia_seguro(hoy.year - 1, 12, dia_corte)
            ultimo_corte = date(hoy.year - 1, 12, ult_dc)
        else:
            ult_dc = dia_seguro(hoy.year, hoy.month - 1, dia_corte)
            ultimo_corte = date(hoy.year, hoy.month - 1, ult_dc)
        proximo_corte = corte_actual
    else:
        # Ya pasó el corte, el próximo es el mes que viene
        ultimo_corte = corte_actual
        if hoy.month == 12:
            prox_dc = dia_seguro(hoy.year + 1, 1, dia_corte)
            proximo_corte = date(hoy.year + 1, 1, prox_dc)
        else:
            prox_dc = dia_seguro(hoy.year, hoy.month + 1, dia_corte)
            proximo_corte = date(hoy.year, hoy.month + 1, prox_dc)

    return ultimo_corte, proximo_corte, dia_pago

def convertir_a_float(valor):
    if pd.isna(valor) or str(valor).strip() == '':
        return 0.0
    texto_limpio = str(valor).replace("S/", "").replace("s/", "").strip()
    try:
        return float(texto_limpio)
    except (ValueError, TypeError):
        return 0.0

# --- DASHBOARD DE TARJETAS ---
st.subheader("💳 Estado de tus cuentas")

if not df_config.empty and not df_transacciones.empty:
    num_tarjetas = len(df_config)
    cols = st.columns(min(num_tarjetas, 4))

    for i, (idx, row) in enumerate(df_config.iterrows()):
        nombre = str(row.get('Tarjeta', 'Sin nombre'))
        tipo = str(row.get('Tipo', 'Credito'))

        try:
            ultimo_corte, proximo_corte, dia_pago = calcular_ciclo_tarjeta(row)
        except Exception as e:
            st.error(f"Error calculando ciclo para {nombre}: {e}")
            continue

        # Filtrar transacciones de esta tarjeta
        df_cuenta = df_transacciones[df_transacciones['Tarjeta'] == nombre]
        df_gastos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Gasto'].copy()
        df_ingresos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Ingreso']

        # Convertir fechas de forma segura
        if not df_gastos_cuenta.empty and 'Fecha' in df_gastos_cuenta.columns:
            df_gastos_cuenta['Fecha_Obj'] = pd.to_datetime(df_gastos_cuenta['Fecha'], format='%d/%m/%Y', errors='coerce')
        else:
            df_gastos_cuenta['Fecha_Obj'] = pd.NaT

        # Gastos del ciclo actual
        mask_ciclo_actual = (df_gastos_cuenta['Fecha_Obj'].dt.date >= ultimo_corte) & (df_gastos_cuenta['Fecha_Obj'].dt.date < proximo_corte)
        total_a_pagar = float(pd.to_numeric(df_gastos_cuenta.loc[mask_ciclo_actual, 'Monto'], errors='coerce').sum()) if not df_gastos_cuenta.empty else 0.0

        # Gastos del siguiente ciclo
        mask_proximo_ciclo = (df_gastos_cuenta['Fecha_Obj'].dt.date >= proximo_corte)
        total_proximo_ciclo = float(pd.to_numeric(df_gastos_cuenta.loc[mask_proximo_ciclo, 'Monto'], errors='coerce').sum()) if not df_gastos_cuenta.empty else 0.0

        # Cálculos seguros de saldos
        limite = convertir_a_float(row.get('Limite_Credito', 0))

        total_ingresos_cuenta = 0.0
        if not df_ingresos_cuenta.empty and 'Monto' in df_ingresos_cuenta.columns:
            total_ingresos_cuenta = float(pd.to_numeric(df_ingresos_cuenta['Monto'], errors='coerce').sum())

        total_gastos_sin_filtro = 0.0
        if not df_gastos_cuenta.empty and 'Monto' in df_gastos_cuenta.columns:
            total_gastos_sin_filtro = float(pd.to_numeric(df_gastos_cuenta['Monto'], errors='coerce').sum())

        total_comisiones = 0.0
        if not df_gastos_cuenta.empty and 'Comision' in df_gastos_cuenta.columns:
            total_comisiones = float(pd.to_numeric(df_gastos_cuenta['Comision'], errors='coerce').fillna(0).sum())

        if tipo == 'Debito':
            saldo_disponible = total_ingresos_cuenta - total_gastos_sin_filtro
        else:
            saldo_disponible = limite - total_gastos_sin_filtro - total_comisiones

        # --- RENDERIZADO ---
        with cols[i % 4]:
            st.markdown(f"### 🏦 {nombre}")

            if tipo == 'Credito':
                c1, c2 = st.columns(2)
                c1.metric(label="💰 Deuda actual a pagar", value=f"S/ {total_a_pagar:,.2f}")

                pct_uso_actual = (total_a_pagar / limite * 100) if limite > 0 else 0
                if pct_uso_actual > 90:
                    c2.error(f"🚨 ¡Cuidado! Debes S/ {total_a_pagar:,.2f}")
                elif pct_uso_actual > 70:
                    c2.warning(f"⚠️ Alto consumo: S/ {total_a_pagar:,.2f}")
                else:
                    c2.success(f"✅ Deuda controlada: S/ {total_a_pagar:,.2f}")

                st.success(f"📅 Pago sugerido: día {dia_pago}")

                if total_proximo_ciclo > 0:
                    st.caption(f"🗓️ Compras después del corte (mes siguiente): S/ {total_proximo_ciclo:,.2f}")

                st.metric(label="📊 Saldo disponible actual", value=f"S/ {saldo_disponible:,.2f}")

                pct_uso_total = ((total_gastos_sin_filtro + total_comisiones) / limite) * 100 if limite > 0 else 0
                st.progress(min(pct_uso_total / 100, 1.0))
                st.caption(f"Usado: {pct_uso_total:.1f}% de S/ {limite:,.2f}")

                if total_comisiones > 0:
                    st.warning(f"💸 Comisiones por ruleteo este mes: S/ {total_comisiones:,.2f}")

            else:
                st.metric(label="💰 Saldo disponible", value=f"S/ {saldo_disponible:,.2f}")
                if saldo_disponible < 0:
                    st.error("⚠️ ¡Estás en números rojos!")
                else:
                    st.info("💡 Este es tu dinero real (no crédito).")

# --- 3. ASESOR FINANCIERO (CON GRÁFICOS PLOTLY) ---
st.divider()
st.subheader("📊 Análisis y recomendaciones")
if not df_procesado.empty:
    df_gastos_proc = df_procesado[df_procesado['Tipo'] == 'Gasto']
    total_ingresos = df_procesado[df_procesado['Tipo'] == 'Ingreso']['Monto'].sum()
    total_gastos = df_gastos_proc['Monto'].sum()

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
                st.warning(f"💸 Gastaste S/ {gastos_impulsivos:,.2f} en impulsos ({pct_imp:.1f}% de ingresos).")
                if pct_imp > 15: st.markdown("📉 **Consejo:** Aplica la regla de 30 días.")
            else: st.success("🎉 Sin gastos impulsivos!")

            fijos = df_procesado[df_procesado['Fijo_Detectado'] == 'Sí (Auto)']
            if not fijos.empty: st.info(f"📌 Detecté {len(fijos)} gastos fijos.")
            st.success(f"💰 Meta de ahorro sugerida: 10% = S/ {total_ingresos * 0.1:,.2f}")

# --- 4. FORMULARIO ---
st.divider()
st.subheader("✏️ Registrar nuevo movimiento")
with st.form("form_registro"):
    fecha = st.date_input("Fecha", datetime.now())
    descripcion = st.text_input("Descripción *", placeholder="Ej: Compra en Zara")
    categoria = st.text_input("Categoría", placeholder="Ej: Ropa")
    monto = st.number_input("Monto (S/)", min_value=0.01, step=0.5, format="%.2f")
    tipo = st.selectbox("Tipo", ["Gasto", "Ingreso"])

    opciones_tarjetas = ["No aplica"]
    if not df_config.empty and 'Tarjeta' in df_config.columns:
        opciones_tarjetas.extend(df_config['Tarjeta'].tolist())
    tarjeta = st.selectbox("Tarjeta/Cuenta asociada", opciones_tarjetas)

    es_ruleteo = st.checkbox("⚡ ¿Esto fue un Ruleteo? (Avance/Transferencia)")
    comision_ruleteo = 0.0
    if es_ruleteo:
        st.caption("Las entidades suelen cobrar comisión por esto.")
        comision_ruleteo = st.number_input("Comisión por el ruleteo (S/)", min_value=0.0, step=1.0, format="%.2f")

    es_fijo = st.checkbox("¿Es un gasto fijo mensual?")

    submitted = st.form_submit_button("Guardar movimiento")
    if submitted:
        error = False
        if not descripcion.strip():
            st.error("❌ La 'Descripción' es obligatoria."); error = True
        if monto <= 0:
            st.error("❌ El 'Monto' debe ser mayor a 0."); error = True

        if not error:
            nueva_fila = [
                fecha.strftime("%d/%m/%Y"),
                descripcion.strip(),
                categoria.strip() if categoria.strip() else "Sin categoría",
                monto,
                tipo,
                tarjeta,
                "Sí" if es_fijo else "No",
                comision_ruleteo
            ]
            if escribir_fila("Transacciones", nueva_fila):
                st.success("✅ Guardado correctamente")
                st.balloons(); st.rerun()

# --- 5. TABLA ---
st.divider()
st.subheader("📋 Historial completo")
if not df_procesado.empty:
    columnas_mostrar = ['Fecha', 'Descripcion', 'Categoria', 'Monto', 'Tipo', 'Tarjeta', 'Clasificacion', 'Fijo_Detectado']
    columnas_existentes = [col for col in columnas_mostrar if col in df_procesado.columns]
    st.dataframe(df_procesado[columnas_existentes], use_container_width=True)
    st.caption(f"Total: {len(df_procesado)} movimientos")
else:
    st.info("Aún no hay transacciones.")