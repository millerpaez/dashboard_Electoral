import pandas as pd
import streamlit as st
import plotly.express as px
import numpy as np
import re
import gspread
from google.oauth2.service_account import Credentials

def get_sheet_names():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key("1OjsW5-Kd39c23no6NBdNJiQXsQngQ3yncyBUAlcK7AA")
    return [ws.title for ws in spreadsheet.worksheets()], spreadsheet

def load_data(sheet_name):
    _, spreadsheet = get_sheet_names()
    sheet = spreadsheet.worksheet(sheet_name)
    df = pd.DataFrame(sheet.get_all_records())

    df = df.copy()

    # Cedula: columna 0 ('-')
    df['cedula'] = df.iloc[:, 0].astype(str).str.strip()

    # Lider: columna 'lider' - normalizar espacios multiples
    lider_col = df.columns.get_loc('lider')
    df['lider'] = df.iloc[:, lider_col].astype(str).str.strip()
    df['lider'] = df['lider'].apply(lambda x: re.sub(r'\s+', ' ', x))

    # Sub_lider: si existe, normalizar y usar como filtro de lideres
    if 'sub_lider' in df.columns:
        df['sub_lider'] = df['sub_lider'].astype(str).str.strip()
        df['sub_lider'] = df['sub_lider'].apply(lambda x: re.sub(r'\s+', ' ', x))
        df['lider_filtro'] = df['sub_lider']
    else:
        df['lider_filtro'] = df['lider']

    # Ciudad: columna 'mun_votacion'
    ciudad_col = df.columns.get_loc('mun_votacion')
    df['ciudad'] = df.iloc[:, ciudad_col].astype(str).str.strip()

    # Cumplio
    cumplio_col = df.columns.get_loc('cumplio')
    df['cumplio_raw'] = df.iloc[:, cumplio_col].astype(str).str.strip().str.upper()
    df['cumplio'] = df['cumplio_raw'].map({'SI': 1, 'NO': 0, '': -1, 'NAN': -1}).fillna(-1).astype(int)

    # Condicionado
    cond_col = df.columns.get_loc('Condicionado')
    df['Condicionado_raw'] = df.iloc[:, cond_col].astype(str).str.strip().str.upper()
    df['Condicionado'] = df['Condicionado_raw'].map({'SI': 1, 'NO': 0, '': 0, 'NAN': 0}).fillna(0).astype(int)

    # Metrica condicionado solo si cumplio
    df['condicionado_si_cumplio'] = np.where(df['cumplio'] == 1, df['Condicionado'], 0)

    return df

def filter_data(df, selected_ciudades, selected_lideres):
    filtered = df.copy()
    if selected_ciudades:
        filtered = filtered[filtered['ciudad'].isin(selected_ciudades)]
    if selected_lideres:
        filtered = filtered[filtered['lider_filtro'].isin(selected_lideres)]
    return filtered

def calculate_metrics(df_filtered):
    total = len(df_filtered)
    cumplidos = (df_filtered['cumplio'] == 1).sum()
    no_cumplidos = (df_filtered['cumplio'] == 0).sum()
    sin_procesar = (df_filtered['cumplio'] == -1).sum()
    condicionados = df_filtered['condicionado_si_cumplio'].sum()
    procesados = cumplidos + no_cumplidos

    return {
        'total': total,
        'cumplidos': cumplidos,
        'no_cumplidos': no_cumplidos,
        'sin_procesar': sin_procesar,
        'pct_cumplidos': round((cumplidos/procesados)*100, 1) if procesados > 0 else 0,
        'pct_no_cumplidos': round((no_cumplidos/procesados)*100, 1) if procesados > 0 else 0,
        'condicionados': condicionados,
        'pct_condicionados': round((condicionados/cumplidos)*100, 1) if cumplidos > 0 else 0
    }

def create_charts(df_filtered, selected_ciudades, selected_lideres):
    # Solo registros procesados para el grafico de cumplimiento general
    df_procesados = df_filtered[df_filtered['cumplio'] != -1]
    cumplidos = (df_procesados['cumplio'] == 1).sum()
    no_cumplidos = (df_procesados['cumplio'] == 0).sum()
    
    fig1 = px.pie(
        values=[cumplidos, no_cumplidos],
        names=['Cumplieron', 'No Cumplieron'],
        title='Cumplimiento General (Solo Procesados)',
        color_discrete_map={'Cumplieron': '#10B981', 'No Cumplieron': '#EF4444'}
    )

    cumplidos_data = df_filtered[df_filtered['cumplio'] == 1]
    fig2 = px.pie(
        values=[cumplidos_data['condicionado_si_cumplio'].sum(), 
                len(cumplidos_data) - cumplidos_data['condicionado_si_cumplio'].sum()],
        names=['Condicionados', 'Sin Condicion'],
        title='Estado de Cumplidos',
        color_discrete_map={'Condicionados': '#F59E0B', 'Sin Condicion': '#10B981'}
    )

    if selected_ciudades and not selected_lideres:
        bar_data = df_filtered[df_filtered['cumplio'] != -1].groupby('lider_filtro')['cumplio'].agg(['sum', 'count']).reset_index()
        bar_data['pct'] = (bar_data['sum'] / bar_data['count']) * 100
        fig3 = px.bar(bar_data, x='lider_filtro', y='pct', title='Cumplimiento por Lider', color='pct', color_continuous_scale='RdYlGn')
    elif selected_lideres and not selected_ciudades:
        bar_data = df_filtered[df_filtered['cumplio'] != -1].groupby('ciudad')['cumplio'].agg(['sum', 'count']).reset_index()
        bar_data['pct'] = (bar_data['sum'] / bar_data['count']) * 100
        fig3 = px.bar(bar_data, x='ciudad', y='pct', title='Cumplimiento por Ciudad', color='pct', color_continuous_scale='RdYlGn')
    else:
        fig3 = px.bar(title='Selecciona filtros para barras')

    return fig1, fig2, fig3

# ========== DASHBOARD ==========
st.set_page_config(page_title="Dashboard Electoral", layout="wide")

st.title("Dashboard Electoral")
st.markdown("**Analisis de cumplimiento electoral**")

try:
    sheet_names, _ = get_sheet_names()
except Exception as e:
    st.error(f"Error al conectar con Google Sheets: {e}")
    st.stop()

# Selector de hoja
st.sidebar.header("Filtros")
selected_sheet = st.sidebar.selectbox("Hoja", sheet_names)

try:
    df = load_data(selected_sheet)
except Exception as e:
    st.error(f"Error al cargar datos: {e}")
    st.stop()

# Filtros
ciudades = sorted(df['ciudad'].dropna().unique())
lider_label = "Sub-Lideres" if 'sub_lider' in df.columns else "Lideres"
lideres = sorted(df['lider_filtro'].dropna().unique())

selected_ciudades = st.sidebar.multiselect("Ciudades", ciudades)
selected_lideres = st.sidebar.multiselect(lider_label, lideres)

if st.sidebar.button("Actualizar", type="primary"):
    st.cache_data.clear()
    st.rerun()

df_filtered = filter_data(df, selected_ciudades, selected_lideres)
metrics = calculate_metrics(df_filtered)

# Metricas
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total", metrics['total'])
col2.metric("Cumplieron", metrics['cumplidos'], f"{metrics['pct_cumplidos']}%")
col3.metric("No Cumplieron", metrics['no_cumplidos'], f"-{metrics['pct_no_cumplidos']}%")
col4.metric("Sin Procesar", metrics['sin_procesar'])

col5, col6 = st.columns(2)
col5.metric("Condicionados", metrics['condicionados'], f"{metrics['pct_condicionados']}%")
col6.metric("Procesados", metrics['cumplidos'] + metrics['no_cumplidos'])

# Graficos
fig1, fig2, fig3 = create_charts(df_filtered, selected_ciudades, selected_lideres)
col_g1, col_g2 = st.columns(2)
col_g1.plotly_chart(fig1, use_container_width=True)
col_g2.plotly_chart(fig2, use_container_width=True)
st.plotly_chart(fig3, use_container_width=True)

# Tabla
st.subheader("Datos")
df_display_filtered = df_filtered[['cedula', 'nombre', 'lider', 'ciudad', 'puesto_votacion', 'mesa', 'cumplio', 'Condicionado']].copy()
df_display_filtered['estado'] = df_display_filtered['cumplio'].map({1: 'Cumplio', 0: 'No Cumplio', -1: 'Sin Procesar'})
st.dataframe(df_display_filtered[['cedula', 'nombre', 'lider', 'ciudad', 'puesto_votacion', 'mesa', 'estado', 'Condicionado']].head(500), use_container_width=True)

st.caption(f"Filtros: {len(selected_ciudades)} ciudades, {len(selected_lideres)} lideres | Procesados: {metrics['cumplidos'] + metrics['no_cumplidos']} | Sin procesar: {metrics['sin_procesar']} | Mostrando primeros 500 registros")
