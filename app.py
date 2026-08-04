import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
import plotly.graph_objects as go
import plotly.express as px
import json

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

# --- NUEVO: LÓGICA DE CICLO DE FACTURACIÓN (CORTE, PAGO Y SALDO DISPONIBLE) ---
hoy = date.today()

# Función para calcular corte/pago según la configuración de la tarjeta
def calcular_ciclo_tarjeta(row_config):
    try:
        # El código busca columnas llamadas "Dia_Corte" y "Dia_Pago" (números)
        dia_corte = int(row_config.get('Dia_Corte', 15)) 
        dia_pago = int(row_config.get('Dia_Pago', 5))   
    except:
        dia_corte = 15
        dia_pago = 5

    # Determinamos la fecha de corte más reciente
    corte_actual = date(hoy.year, hoy.month, dia_corte)
    if hoy < corte_actual:
        ultimo_corte = date(hoy.year, hoy.month - 1, dia_corte) if hoy.month > 1 else date(hoy.year - 1, 12, dia_corte)
        proximo_corte = corte_actual
    else:
        ultimo_corte = corte_actual
        if hoy.month == 12:
            proximo_corte = date(hoy.year + 1, 1, dia_corte)
        else:
            proximo_corte = date(hoy.year, hoy.month + 1, dia_corte)
            
    return ultimo_corte, proximo_corte, dia_pago

# --- DASHBOARD DE TARJETAS ---
st.subheader("💳 Estado de tus cuentas")

if not df_config.empty and not df_transacciones.empty:
    num_tarjetas = len(df_config)
    cols = st.columns(min(num_tarjetas, 4))
    
    for i, (idx, row) in enumerate(df_config.iterrows()):
        nombre = row.get('Tarjeta', 'Sin nombre')
        tipo = row.get('Tipo', 'Credito')
        limite = float(row.get('Limite_Credito', 0))
        
        # Calcular ciclos para esta tarjeta (ahora devuelve también el día de pago)
        ultimo_corte, proximo_corte, dia_pago = calcular_ciclo_tarjeta(row)
        
        # 1. Filtrar gastos e ingresos de esta tarjeta
        df_cuenta = df_transacciones[df_transacciones['Tarjeta'] == nombre]
        df_gastos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Gasto']
        
        # Convertir columna Fecha a datetime para filtrar por rango
        df_gastos_cuenta['Fecha_Obj'] = pd.to_datetime(df_gastos_cuenta['Fecha'], format='%d/%m/%Y')
        
        # GASTOS DEL CICLO ACTUAL (Lo que debe pagar este mes)
        mask_ciclo_actual = (df_gastos_cuenta['Fecha_Obj'].dt.date >= ultimo_corte) & (df_gastos_cuenta['Fecha_Obj'].dt.date < proximo_corte)
        total_a_pagar = df_gastos_cuenta.loc[mask_ciclo_actual, 'Monto'].sum()
        
        # GASTOS DEL SIGUIENTE CICLO (Compras después del próximo corte)
        mask_proximo_ciclo = (df_gastos_cuenta['Fecha_Obj'].dt.date >= proximo_corte)
        total_proximo_ciclo = df_gastos_cuenta.loc[mask_proximo_ciclo, 'Monto'].sum()
        
        # SALDO DISPONIBLE
        total_ingresos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Ingreso']['Monto'].sum()
        total_gastos_sin_filtro = df_gastos_cuenta['Monto'].sum()
        
        if tipo == 'Debito':
            saldo_disponible = total_ingresos_cuenta - total_gastos_sin_filtro
        else:
            total_comisiones = df_gastos_cuenta['Comision'].sum() if 'Comision' in df_gastos_cuenta.columns else 0
            saldo_disponible = limite - total_gastos_sin_filtro - total_comisiones

        with cols[i % 4]:
            st.markdown(f"### 🏦 {nombre}")
            
            # DATOS DEL CICLO DE CRÉDITO
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

                # Aquí es donde mostramos el día de pago sugerido
                st.success(f"📅 Pago sugerido: día {dia_pago}")

                if total_proximo_ciclo > 0:
                    st.caption(f"🗓️ Compras después del corte (mes siguiente): S/ {total_proximo_ciclo:,.2f}")

                st.metric(label="📊 Saldo disponible actual", value=f"S/ {saldo_disponible:,.2f}")
                
                pct_uso_total = ((total_gastos_sin_filtro + total_comisiones) / limite) * 100 if limite > 0 else 0
                st.progress(min(pct_uso_total / 100, 1.0))
                st.caption(f"Usado: {pct_uso_total:.1f}% de S/ {limite:,.2f}")

                # Alerta por Ruleteo y Comisiones
                if 'Comision' in df_gastos_cuenta.columns:
                    total_comision = df_gastos_cuenta['Comision'].sum()
                    if total_comision > 0:
                        st.warning(f"💸 Comisiones por ruleteo este mes: S/ {total_comision:,.2f}")
            
            else:
                # Para Débito
                st.metric(label="💰 Saldo disponible", value=f"S/ {saldo_disponible:,.2f}")
                if saldo_disponible < 0:
                    st.error("⚠️ ¡Estás en números rojos!")
                else:
                    st.info("💡 Este es tu dinero real (no crédito).")

# --- DASHBOARD DE TARJETAS ---
st.subheader("💳 Estado de tus cuentas")

if not df_config.empty and not df_transacciones.empty:
    df_gastos = df_transacciones[df_transacciones['Tipo'] == 'Gasto']
    num_tarjetas = len(df_config)
    cols = st.columns(min(num_tarjetas, 4))
    
    for i, (idx, row) in enumerate(df_config.iterrows()):
        nombre = row.get('Tarjeta', 'Sin nombre')
        tipo = row.get('Tipo', 'Credito')
        limite = float(row.get('Limite_Credito', 0))
        
        # Calcular ciclos para esta tarjeta
        ultimo_corte, proximo_corte = calcular_ciclo_tarjeta(row)
        
        # 1. Filtrar gastos e ingresos de esta tarjeta
        df_cuenta = df_transacciones[df_transacciones['Tarjeta'] == nombre]
        df_gastos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Gasto']
        
        # Convertir columna Fecha a datetime para filtrar por rango
        df_gastos_cuenta['Fecha_Obj'] = pd.to_datetime(df_gastos_cuenta['Fecha'], format='%d/%m/%Y')
        
        # GASTOS DEL CICLO ACTUAL (Lo que debe pagar este mes)
        # Gastos realizados entre el último corte y el próximo corte
        mask_ciclo_actual = (df_gastos_cuenta['Fecha_Obj'].dt.date >= ultimo_corte) & (df_gastos_cuenta['Fecha_Obj'].dt.date < proximo_corte)
        total_a_pagar = df_gastos_cuenta.loc[mask_ciclo_actual, 'Monto'].sum()
        
        # GASTOS DEL SIGUIENTE CICLO (Compras después del próximo corte)
        mask_proximo_ciclo = (df_gastos_cuenta['Fecha_Obj'].dt.date >= proximo_corte)
        total_proximo_ciclo = df_gastos_cuenta.loc[mask_proximo_ciclo, 'Monto'].sum()
        
        # SALDO DISPONIBLE: Límite - (Total Pagado + Total Próximo + Comisiones)
        # (Si tiene débito, el límite es su saldo a favor)
        total_ingresos_cuenta = df_cuenta[df_cuenta['Tipo'] == 'Ingreso']['Monto'].sum()
        total_gastos_sin_filtro = pd.to_numeric(df_gastos_cuenta['Monto'], errors='coerce').sum()
        
        if tipo == 'Debito':
            saldo_disponible = total_ingresos_cuenta - total_gastos_sin_filtro
        else:
            # Para crédito: restamos todo el gasto y las comisiones del límite
            # (Si no hay datos de comisiones, se asume 0)
            total_comisiones = pd.to_numeric(df_gastos_cuenta['Comision'], errors='coerce').sum() if 'Comision' in df_gastos_cuenta.columns else 0
            saldo_disponible = limite - total_gastos_sin_filtro - total_comisiones

        with cols[i % 4]:
            st.markdown(f"### 🏦 {nombre}")
            
            # DATOS DEL CICLO DE CRÉDITO (Para tarjetas de crédito)
            if tipo == 'Credito':
                c1, c2 = st.columns(2)
                c1.metric(label="💰 Deuda actual a pagar", value=f"S/ {total_a_pagar:,.2f}")
                
                # Calculamos el porcentaje de uso considerando solo lo que debe pagar ahora
                pct_uso_actual = (total_a_pagar / limite * 100) if limite > 0 else 0
                if pct_uso_actual > 90:
                    c2.error(f"🚨 ¡Cuidado! Debes S/ {total_a_pagar:,.2f}")
                elif pct_uso_actual > 70:
                    c2.warning(f"⚠️ Alto consumo: S/ {total_a_pagar:,.2f}")
                else:
                    c2.success(f"✅ Deuda controlada: S/ {total_a_pagar:,.2f}")

                # Mostrar compras del siguiente ciclo
                if total_proximo_ciclo > 0:
                    st.caption(f"🗓️ Compras después del corte (mes siguiente): S/ {total_proximo_ciclo:,.2f}")

                # Mostrar saldo disponible total
                st.metric(label="📊 Saldo disponible actual", value=f"S/ {saldo_disponible:,.2f}")
                
                # Barra de progreso del límite total
                pct_uso_total = ((total_gastos_sin_filtro + total_comisiones) / limite) * 100 if limite > 0 else 0
                st.progress(min(pct_uso_total / 100, 1.0))
                st.caption(f"Usado: {pct_uso_total:.1f}% de S/ {limite:,.2f}")

                # Alerta por Ruleteo y Comisiones
                if 'Comision' in df_gastos_cuenta.columns:
                    total_comision = df_gastos_cuenta['Comision'].sum()
                    if total_comision > 0:
                        st.warning(f"💸 Comisiones por ruleteo este mes: S/ {total_comision:,.2f}")
            
            else:
                # Para Débito
                st.metric(label="💰 Saldo disponible", value=f"S/ {saldo_disponible:,.2f}")

# (El resto del código sigue igual: Análisis, Formulario y Tabla)
# --- 3. ASESOR FINANCIERO ---
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
                color_discrete_map={'Impulsivo':'red', 'Necesario':'green', 'Sin clasificar':'gray'}
            )
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
    
    # Agregamos opción para Ruleteo
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
                comision_ruleteo  # <-- Nueva columna: Comisión
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