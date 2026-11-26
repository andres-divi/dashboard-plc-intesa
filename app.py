import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import re
from pathlib import Path

# ── Logo e ícono de pestaña ────────────────────────────────────────────────
_logo_path = Path("logo/logoo.jpeg")
_page_icon = "🏭"
if _logo_path.exists():
    from PIL import Image as _PILImage
    _page_icon = _PILImage.open(_logo_path)

# Configuración de la página
st.set_page_config(
    page_title="Dashboard PLC - INTESA",
    layout="wide",
)


# ── Encabezado con logo ────────────────────────────────────────────────────
_col_logo, _col_titulo = st.columns([1, 5], vertical_alignment="center")
with _col_logo:
    if _logo_path.exists():
        st.image(str(_logo_path), width=130)
with _col_titulo:
    st.title("📊 Análisis de Datos de PLC - INTESA")
    st.write("Sube uno o más archivos de registro de datos (CSV o Excel) para visualizar las variables de los sensores en el tiempo.")

# ──────────────────────────────────────────────
# Función: Normalizar horas con AM/PM a formato 24h
# ──────────────────────────────────────────────
def normalizar_ampm(serie: pd.Series) -> pd.Series:
    """
    Convierte horas en formato 12h a 24h.
    Maneja todos los formatos que exporta el PLC:
      - Inglés:  '2:38:08 PM',  '10:05 AM'
      - Español: '2:38:08 p. m.',  '10:05 a. m.'
      - También funciona si la celda tiene fecha + hora: '30/4/2026 2:38:08 p. m.'
    """
    muestra = serie.dropna().astype(str).head(50)
    # Detectar cualquier variante: AM, PM, a.m., p.m., a. m., p. m.
    tiene_ampm = muestra.str.contains(
        r'[AaPp]\.?\s*[Mm]\.?', regex=True
    ).any()
    if not tiene_ampm:
        return serie

    # Patrón que captura la hora + indicador AM/PM (en cualquier variante)
    PATRON = re.compile(
        r'(\d{1,2}):(\d{2})(?::(\d{2}))?\s*'   # H:MM o H:MM:SS
        r'([AaPp])\.?\s*([Mm])\.?',              # AM/PM / a.m. / p. m. etc.
        re.IGNORECASE
    )

    def convertir(valor):
        s = str(valor).strip()
        m = PATRON.search(s)
        if not m:
            return s
        h  = int(m.group(1))
        mi = int(m.group(2))
        sc = int(m.group(3) or 0)
        periodo = (m.group(4) + m.group(5)).upper()  # 'AM' o 'PM'

        if periodo == 'AM':
            h = 0 if h == 12 else h        # 12:xx AM → 00:xx
        else:
            h = 12 if h == 12 else h + 12  # 12:xx PM → 12:xx, x PM → x+12

        hora_nueva = f"{h:02d}:{mi:02d}:{sc:02d}"
        # Reemplazar el match original dentro del string completo
        return (s[:m.start()] + hora_nueva + s[m.end():]).strip()

    return serie.astype(str).apply(convertir)


# ──────────────────────────────────────────────
# Función: cargar un único archivo
# ──────────────────────────────────────────────
@st.cache_data
def load_single_file(file_bytes: bytes, file_name: str, sep: str = ',') -> pd.DataFrame | None:
    """
    Carga un archivo CSV o Excel desde bytes.
    - Separador: configurable (',' o ';')
    - Decimal: automático según separador (';' → decimal=',', ',' → decimal='.')
    - Prueba encodings: utf-8-sig (BOM), utf-8, latin-1, cp1252
    - Conversión de respaldo: columnas texto con ≥80% números se convierten a float
    """
    import io

    ENCODINGS = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]

    # Si el separador es ';', el decimal probablemente es ',' (estándar europeo/latinoamericano)
    # Si el separador es ',', el decimal es '.' (estándar anglosajón)
    decimal_char = ',' if sep == ';' else '.'

    try:
        if file_name.endswith('.csv'):
            df = None
            last_error = None
            for enc in ENCODINGS:
                try:
                    df = pd.read_csv(
                        io.BytesIO(file_bytes),
                        sep=sep,
                        decimal=decimal_char,
                        encoding=enc,
                        low_memory=False,
                        on_bad_lines='skip',
                    )
                    break  # Si funcionó, salir del loop
                except Exception as e:
                    last_error = e
                    continue

            if df is None:
                # Último intento: engine Python sin encoding fijo
                try:
                    df = pd.read_csv(
                        io.BytesIO(file_bytes),
                        sep=sep,
                        decimal=decimal_char,
                        encoding='latin-1',
                        low_memory=False,
                        engine='python',
                        on_bad_lines='skip',
                    )
                except Exception as e:
                    st.error(f"No se pudo leer '{file_name}': {e}")
                    return None

        elif file_name.endswith('.xlsx'):
            df = pd.read_excel(io.BytesIO(file_bytes))
        else:
            st.error(f"Formato no soportado: {file_name}")
            return None

        # ── Conversión de respaldo ──────────────────────────────────────────
        # Columnas que quedaron como texto pero contienen números
        # (puede pasar con decimal mixto o encoding raro)
        for col in df.select_dtypes(include='object').columns:
            convertida = (
                df[col].astype(str)
                .str.strip()
                .str.replace(',', '.', regex=False)  # coma decimal → punto
            )
            intentado = pd.to_numeric(convertida, errors='coerce')
            # Solo reemplazar si al menos el 80 % de las filas son numéricas
            ratio = intentado.notna().mean()
            if ratio >= 0.8:
                df[col] = intentado

        return df
    except Exception as e:
        st.error(f"Error al procesar '{file_name}': {e}")
        return None


# 1. Interfaz de carga — múltiples archivos
col_upload, col_sep = st.columns([3, 1])

with col_sep:
    sep_opcion = st.radio(
        "Separador CSV",
        options=["Coma  ( , )", "Punto y coma  ( ; )"],
        index=0,
        help="Elegí el separador que usa tu archivo CSV del PLC.",
    )
    sep_char = "," if sep_opcion.startswith("Coma") else ";"

with col_upload:
    uploaded_files = st.file_uploader(
        "Arrastrá y soltá uno o más archivos aquí (.csv, .xlsx)",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
    )

# ──────────────────────────────────────────────
# Sección de bienvenida con mensaje especial
# ──────────────────────────────────────────────
if not uploaded_files:
    st.markdown("---")

    st.markdown(
        """
        <div style="text-align: center; padding: 10px 0 4px 0;">
            <span style="font-size: 2rem;">💙</span>
            <h2 style="font-family: Georgia, serif; font-weight: normal; color: #a8c8f0; margin: 6px 0 2px 0;">
                Hecho con el amor de un hijo a su madre
            </h2>
            <p style="color: #7a9ec0; font-size: 1.05rem; margin: 0 0 6px 0;">
                Esta herramienta fue creada especialmente para vos, para que tu trabajo en 
                <strong style="color:#a8c8f0;">INTESA</strong> sea un poco más fácil cada día. 🏭
            </p>
            <p style="color: #6b8ba4; font-size: 0.95rem; font-style: italic;">
                "Con cariño, dedicación y mucho código." ✨
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)


if uploaded_files:
    # ── Cargar y combinar todos los archivos ──
    dfs = []
    nombres = []
    with st.spinner(f"Cargando {len(uploaded_files)} archivo(s)... ⏳"):
        for uf in uploaded_files:
            file_bytes = uf.read()
            df_i = load_single_file(file_bytes, uf.name, sep=sep_char)
            if df_i is not None:
                dfs.append(df_i)
                nombres.append(uf.name)

    if not dfs:
        st.error("No se pudo cargar ningún archivo.")
        st.stop()

    if len(dfs) == 1:
        df_raw = dfs[0]
        st.success(f"✅ Archivo cargado: **{nombres[0]}** — {len(df_raw):,} registros, {len(df_raw.columns)} columnas.")
    else:
        # Combinar: concatenar verticalmente (las columnas deben coincidir)
        try:
            df_raw = pd.concat(dfs, ignore_index=True, sort=False)
            detalle = " | ".join([f"{n} ({len(d):,} filas)" for n, d in zip(nombres, dfs)])
            st.success(
                f"✅ {len(dfs)} archivos combinados — **{len(df_raw):,} registros totales**\n\n"
                f"📁 {detalle}"
            )
        except Exception as e:
            st.error(f"No se pudieron combinar los archivos: {e}")
            st.stop()

    df = df_raw.copy()

    # Placeholder: se llenará con datos ya ordenados una vez que el timestamp esté listo
    expander_placeholder = st.empty()

    # ===== SIDEBAR =====
    st.sidebar.header("⚙️ Configuración del Gráfico")
    st.sidebar.subheader("Eje X (Tiempo)")

    todas_las_columnas = df.columns.tolist()

    # --- Formato de fecha ---
    FORMATOS_FECHA = {
        "DD/MM/AAAA  (ej: 30/04/2026)": {"dayfirst": True,  "yearfirst": False},
        "MM/DD/AAAA  (ej: 04/30/2026)": {"dayfirst": False, "yearfirst": False},
        "AAAA/MM/DD  (ej: 2026/04/30)": {"dayfirst": False, "yearfirst": True},
        "AAAA-MM-DD  (ej: 2026-04-30)": {"dayfirst": False, "yearfirst": True},
        "DD-MM-AAAA  (ej: 30-04-2026)": {"dayfirst": True,  "yearfirst": False},
        "MM-DD-AAAA  (ej: 04-30-2026)": {"dayfirst": False, "yearfirst": False},
    }
    fmt_elegido = st.sidebar.selectbox(
        "Formato de fecha",
        options=list(FORMATOS_FECHA.keys()),
        index=0,
        help="Elegí el orden en que aparecen día, mes y año en tu archivo.",
    )
    dayfirst_val  = FORMATOS_FECHA[fmt_elegido]["dayfirst"]
    yearfirst_val = FORMATOS_FECHA[fmt_elegido]["yearfirst"]

    st.sidebar.markdown("---")

    # --- Modo: columna única o combinación de Date + Time ---
    modo_fecha = st.sidebar.radio(
        "¿Cómo está el timestamp?",
        options=["Una sola columna (fecha+hora)", "Dos columnas separadas (Date y Time)"],
        index=0,
    )

    col_datetime = None

    if modo_fecha == "Una sola columna (fecha+hora)":
        col_unica = st.sidebar.selectbox(
            "Columna de Fecha/Hora:",
            options=todas_las_columnas,
            index=0,
        )

        # Mostrar valores RAW para diagnóstico
        st.sidebar.caption("📋 Primeros valores:")
        for v in df[col_unica].head(3).astype(str).tolist():
            st.sidebar.code(v, language=None)

        try:
            # Normalizar AM/PM antes de parsear
            serie_normalizada = normalizar_ampm(df[col_unica])
            df["_timestamp"] = pd.to_datetime(
                serie_normalizada,
                dayfirst=dayfirst_val,
                yearfirst=yearfirst_val,
                errors='coerce'
            )
            filas_invalidas = df["_timestamp"].isna().sum()
            if filas_invalidas > 0:
                st.sidebar.warning(f"⚠️ {filas_invalidas} filas con fechas inválidas descartadas.")
                df = df.dropna(subset=["_timestamp"])

            # Ordenar por timestamp y actualizar la tabla
            df = df.sort_values("_timestamp").reset_index(drop=True)
            with expander_placeholder.expander("Ver vista previa y estadísticas de los datos (ordenado por fecha)"):
                st.write(f"**Total de registros:** {len(df):,} | **Columnas:** {len(df.columns)}")
                st.dataframe(df.drop(columns=["_timestamp"]), use_container_width=True, height=600)

            col_datetime = "_timestamp"
            st.sidebar.success(
                f"✅ Rango detectado:\n\n"
                f"**Inicio:** {df[col_datetime].min()}\n\n"
                f"**Fin:** {df[col_datetime].max()}"
            )
        except Exception as ex:
            st.sidebar.error(f"Error al parsear: {ex}")
            # Si falla el parseo, mostrar tabla sin ordenar
            with expander_placeholder.expander("Ver vista previa y estadísticas de los datos"):
                st.write(f"**Total de registros:** {len(df):,} | **Columnas:** {len(df.columns)}")
                st.dataframe(df, use_container_width=True, height=600)

    else:
        # Modo dos columnas: Date + Time separados
        col_date = st.sidebar.selectbox("Columna de Fecha (Date):", options=todas_las_columnas, index=0)
        col_time = st.sidebar.selectbox(
            "Columna de Hora (Time):",
            options=todas_las_columnas,
            index=1 if len(todas_las_columnas) > 1 else 0,
        )

        st.sidebar.caption("📋 Primeros valores fecha:")
        for v in df[col_date].head(2).astype(str).tolist():
            st.sidebar.code(v, language=None)
        st.sidebar.caption("📋 Primeros valores hora:")
        for v in df[col_time].head(2).astype(str).tolist():
            st.sidebar.code(v, language=None)

        try:
            fecha_str = df[col_date].astype(str).str.strip()
            hora_str  = df[col_time].astype(str).str.strip()

            # Si la fecha ya tiene hora embebida (ej: "2026-05-17 00:00:00"), extraer solo la parte YYYY-MM-DD
            fecha_limpia = fecha_str.str.extract(r'(\d{4}-\d{2}-\d{2})')[0]
            if fecha_limpia.isna().all():
                # Intentar formato DD/MM/YYYY
                fecha_limpia = fecha_str.str.extract(r'(\d{1,2}/\d{1,2}/\d{4})')[0]
            fecha_str = fecha_limpia.fillna(fecha_str)

            # Normalizar AM/PM en la columna de hora
            hora_normalizada = normalizar_ampm(pd.Series(hora_str))

            df["_timestamp"] = pd.to_datetime(
                fecha_str + " " + hora_normalizada,
                dayfirst=dayfirst_val,
                yearfirst=yearfirst_val,
                errors='coerce'
            )
            filas_invalidas = df["_timestamp"].isna().sum()
            if filas_invalidas > 0:
                st.sidebar.warning(f"⚠️ {filas_invalidas} filas con fechas inválidas descartadas.")
                df = df.dropna(subset=["_timestamp"])

            # Ordenar por timestamp y actualizar la tabla
            df = df.sort_values("_timestamp").reset_index(drop=True)
            with expander_placeholder.expander("Ver vista previa y estadísticas de los datos (ordenado por fecha)"):
                st.write(f"**Total de registros:** {len(df):,} | **Columnas:** {len(df.columns)}")
                st.dataframe(df.drop(columns=["_timestamp"]), use_container_width=True, height=600)

            col_datetime = "_timestamp"
            st.sidebar.success(
                f"✅ Timestamp combinado OK\n\n"
                f"**Inicio:** {df[col_datetime].min()}\n\n"
                f"**Fin:** {df[col_datetime].max()}"
            )
        except Exception as ex:
            st.sidebar.error(f"Error al combinar columnas: {ex}")
            # Si falla el parseo, mostrar tabla sin ordenar
            with expander_placeholder.expander("Ver vista previa y estadísticas de los datos"):
                st.write(f"**Total de registros:** {len(df):,} | **Columnas:** {len(df.columns)}")
                st.dataframe(df, use_container_width=True, height=600)

    # --- Selector variables numéricas ---
    st.sidebar.subheader("Eje Y (Sensores)")

    cols_excluir = {"_timestamp", "id"}
    if modo_fecha == "Dos columnas separadas (Date y Time)":
        try:
            cols_excluir.add(col_date)
            cols_excluir.add(col_time)
        except Exception:
            pass

    columnas_numericas = [
        c for c in df.select_dtypes(include=['number']).columns.tolist()
        if c not in cols_excluir and c.lower() != 'id'
    ]

    if not columnas_numericas:
        st.error("El archivo no contiene columnas numéricas válidas para graficar.")
    else:
        variables_seleccionadas = st.sidebar.multiselect(
            "Variables a visualizar:",
            options=columnas_numericas,
            default=columnas_numericas[:1],
        )

        if variables_seleccionadas and col_datetime:

            # df ya viene ordenado desde el bloque de timestamp
            t_min = df[col_datetime].min().to_pydatetime()
            t_max = df[col_datetime].max().to_pydatetime()

            # ── Deslizador de rango temporal ────────────────────────────────
            st.markdown("#### 🕐 Rango de tiempo a visualizar")

            rango = st.slider(
                label="Seleccioná el período",
                min_value=t_min,
                max_value=t_max,
                value=(t_min, t_max),          # por defecto: todo el rango
                format="DD/MM/YY HH:mm",
                label_visibility="collapsed",
            )
            t_desde, t_hasta = rango

            # Filtrar el DataFrame según el rango elegido
            mask = (df[col_datetime] >= t_desde) & (df[col_datetime] <= t_hasta)
            df_plot = df.loc[mask]

            if df_plot.empty:
                st.warning("⚠️ No hay datos en el rango seleccionado.")
            else:
                registros_visibles = len(df_plot)
                total_registros    = len(df)
                st.caption(
                    f"Mostrando **{registros_visibles:,}** de **{total_registros:,}** registros  "
                    f"| Desde **{t_desde.strftime('%d/%m/%Y %H:%M')}** "
                    f"hasta **{t_hasta.strftime('%d/%m/%Y %H:%M')}**"
                )

                # ── Promedio móvil por variable ──────────────────────────────
                # El PLC mide cada pocos segundos y algunas señales quedan "serrucho".
                # Cada variable de cada gráfico puede promediarse cada N mediciones
                # (media móvil centrada; N = 1 deja la señal original).
                def selector_promedios(variables, key_prefix):
                    """Muestra un selector 'promediar cada N mediciones' por variable."""
                    ventanas = {}
                    if not variables:
                        return ventanas
                    st.caption(
                        "🔧 **Promediar cada N mediciones** (1 = sin promedio). "
                        "Sirve para suavizar señales que quedan en serrucho."
                    )
                    n_cols = min(len(variables), 4)
                    cols = st.columns(n_cols)
                    for idx_v, var in enumerate(variables):
                        with cols[idx_v % n_cols]:
                            ventanas[var] = int(st.number_input(
                                var,
                                min_value=1,
                                max_value=10000,
                                value=1,
                                step=1,
                                key=f"{key_prefix}_prom_{var}",
                                help="Cantidad de mediciones seguidas que se promedian para cada punto.",
                            ))
                    return ventanas

                def serie_variable(var, n):
                    """Serie de la variable dentro del rango elegido, promediada cada n mediciones."""
                    serie = df[var]
                    if n > 1:
                        # Se calcula sobre todos los datos para que los bordes del rango no se deformen
                        serie = serie.rolling(window=n, center=True, min_periods=1).mean()
                    return serie.loc[mask]

                def nombre_traza(var, n):
                    return var if n <= 1 else f"{var} (prom. {n})"

                # ── Función auxiliar para crear gráfico ──────────────────────
                def crear_figura(variables, ventanas, df_data, col_dt, titulo):
                    fig = go.Figure()
                    for variable in variables:
                        n = ventanas.get(variable, 1)
                        fig.add_trace(
                            go.Scatter(
                                x=df_data[col_dt],
                                y=serie_variable(variable, n),
                                mode='lines',
                                name=nombre_traza(variable, n),
                                line=dict(width=1),
                            )
                        )
                    fig.update_layout(
                        template='plotly_dark',
                        title=titulo,
                        xaxis_title="Tiempo",
                        yaxis_title="Valores",
                        legend_title="Variables",
                        hovermode="x unified",
                        margin=dict(l=40, r=20, t=50, b=40),
                        xaxis=dict(
                            type='date',
                            tickformat='%H:%M:%S\n%d/%m/%Y',
                            range=[t_desde.isoformat(), t_hasta.isoformat()],
                        ),
                    )
                    return fig

                # ===== GRÁFICO PRINCIPAL =====
                st.markdown("#### 📈 Gráfico 1")
                ventanas_principal = selector_promedios(variables_seleccionadas, "g1")
                fig_principal = crear_figura(
                    variables_seleccionadas, ventanas_principal, df_plot, col_datetime,
                    "Evolución Temporal de Sensores"
                )
                st.plotly_chart(fig_principal, use_container_width=True)

                # ── Inicializar lista de gráficos extra en session_state ──────
                # Cada gráfico extra tiene un id fijo, así al quitar uno del medio
                # los demás conservan sus variables y sus promedios.
                if "graficos_extra" not in st.session_state:
                    st.session_state.graficos_extra = []
                if "proximo_id_grafico" not in st.session_state:
                    st.session_state.proximo_id_grafico = 0
                # Compatibilidad con sesiones abiertas con la versión anterior (lista de variables)
                if any(not isinstance(g, dict) for g in st.session_state.graficos_extra):
                    st.session_state.graficos_extra = []

                # ===== GRÁFICOS EXTRA =====
                ids_a_eliminar = []
                for i, grafico in enumerate(st.session_state.graficos_extra):
                    gid = grafico["id"]
                    st.markdown("---")
                    col_titulo, col_eliminar = st.columns([9, 1])
                    with col_titulo:
                        st.markdown(f"#### 📈 Gráfico {i + 2}")
                    with col_eliminar:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("✕ Quitar", key=f"eliminar_{gid}", type="secondary"):
                            ids_a_eliminar.append(gid)

                    vars_seleccionadas_extra = st.multiselect(
                        f"Variables para el Gráfico {i + 2}:",
                        options=columnas_numericas,
                        default=[v for v in grafico["vars"] if v in columnas_numericas],
                        key=f"vars_grafico_{gid}",
                    )
                    # Guardar selección actualizada
                    grafico["vars"] = vars_seleccionadas_extra

                    if vars_seleccionadas_extra:
                        ventanas_extra = selector_promedios(vars_seleccionadas_extra, f"g{gid}x")
                        fig_extra = crear_figura(
                            vars_seleccionadas_extra, ventanas_extra, df_plot, col_datetime,
                            f"Gráfico {i + 2}"
                        )
                        st.plotly_chart(fig_extra, use_container_width=True)
                    else:
                        st.info("👈 Seleccioná al menos una variable para este gráfico.")

                # Eliminar gráficos marcados
                if ids_a_eliminar:
                    st.session_state.graficos_extra = [
                        g for g in st.session_state.graficos_extra if g["id"] not in ids_a_eliminar
                    ]
                    st.rerun()

                # ── Botón para agregar nuevo gráfico ─────────────────────────
                st.markdown("---")
                if st.button("➕  Agregar otro gráfico", use_container_width=True, type="primary"):
                    st.session_state.graficos_extra.append({
                        "id": st.session_state.proximo_id_grafico,
                        "vars": columnas_numericas[:1],
                    })
                    st.session_state.proximo_id_grafico += 1
                    st.rerun()

                # ══════════════════════════════════════════════════════════════
                # SUPERPOSICIÓN DE VARIABLES CON EJES INDEPENDIENTES
                # ══════════════════════════════════════════════════════════════
                st.markdown("---")
                st.markdown("#### 🔀 Superponer variables con ejes independientes")
                st.caption(
                    "Graficá múltiples variables en un mismo panel. "
                    "Cada variable tiene su **propio eje Y** y su **propio color**, "
                    "lo que permite comparar magnitudes muy distintas (ej: presión y temperatura)."
                )

                vars_superponer = st.multiselect(
                    "Variables a superponer:",
                    options=columnas_numericas,
                    default=[],
                    key="vars_superponer",
                    help="Elegí 2 o más variables para ver su superposición con ejes independientes.",
                )

                if vars_superponer:
                    COLORES_SUPER = [
                        '#00d4ff', '#ff6b6b', '#ffd93d', '#6bcb77',
                        '#a855f7', '#fb923c', '#ec4899', '#14b8a6',
                        '#f59e0b', '#3b82f6',
                    ]

                    # ── Promedio por variable ─────────────────────────────────
                    ventanas_super = selector_promedios(vars_superponer, "super")
                    series_super = {
                        var: serie_variable(var, ventanas_super.get(var, 1))
                        for var in vars_superponer
                    }

                    # ── Calcular escala automática como base ───────────────────
                    escalas = {}
                    for var in vars_superponer:
                        v_min_d = float(series_super[var].min())
                        v_max_d = float(series_super[var].max())
                        margen  = (v_max_d - v_min_d) * 0.1 if v_max_d != v_min_d else 1.0
                        escalas[var] = (v_min_d - margen, v_max_d + margen)

                    # ── Expander de ajuste de escala por variable ─────────────
                    with st.expander("⚙️ Ajustar escala de cada variable", expanded=False):
                        n_cols_esc = min(len(vars_superponer), 3)
                        cols_esc   = st.columns(n_cols_esc)
                        for idx, var in enumerate(vars_superponer):
                            with cols_esc[idx % n_cols_esc]:
                                color_var = COLORES_SUPER[idx % len(COLORES_SUPER)]
                                st.markdown(
                                    f"<span style='color:{color_var}; font-weight:700; "
                                    f"font-size:0.95rem;'>■ {var}</span>",
                                    unsafe_allow_html=True,
                                )
                                col_min_i, col_max_i = st.columns(2)
                                with col_min_i:
                                    min_usr = st.number_input(
                                        "Mín",
                                        value=round(escalas[var][0], 6),
                                        key=f"super_min_{var}",
                                        format="%g",
                                    )
                                with col_max_i:
                                    max_usr = st.number_input(
                                        "Máx",
                                        value=round(escalas[var][1], 6),
                                        key=f"super_max_{var}",
                                        format="%g",
                                    )
                                escalas[var] = (min_usr, max_usr)

                    # ── Construir figura con múltiples ejes Y ─────────────────
                    n_vars   = len(vars_superponer)
                    n_right  = max(0, n_vars - 1)
                    # El dominio X se achica para hacer lugar a los ejes derechos
                    x_end    = max(0.55, 1.0 - n_right * 0.09)

                    fig_super = go.Figure()

                    for idx, var in enumerate(vars_superponer):
                        color     = COLORES_SUPER[idx % len(COLORES_SUPER)]
                        yaxis_ref = 'y' if idx == 0 else f'y{idx + 1}'
                        fig_super.add_trace(go.Scatter(
                            x=df_plot[col_datetime],
                            y=series_super[var],
                            mode='lines',
                            name=nombre_traza(var, ventanas_super.get(var, 1)),
                            line=dict(color=color, width=1),
                            yaxis=yaxis_ref,
                        ))

                    layout_super = dict(
                        template='plotly_dark',
                        title='🔀 Superposición de Variables',
                        xaxis=dict(
                            title='Tiempo',
                            type='date',
                            tickformat='%H:%M:%S\n%d/%m/%Y',
                            range=[t_desde.isoformat(), t_hasta.isoformat()],
                        ),
                        hovermode='x unified',
                        margin=dict(l=60, r=20, t=65, b=40),
                        legend=dict(
                            orientation='h',
                            yanchor='bottom', y=1.06,
                            xanchor='left', x=0,
                        ),
                        height=540,
                    )

                    for idx, var in enumerate(vars_superponer):
                        color      = COLORES_SUPER[idx % len(COLORES_SUPER)]
                        min_v, max_v = escalas[var]
                        yaxis_key  = 'yaxis' if idx == 0 else f'yaxis{idx + 1}'

                        if idx == 0:
                            layout_super[yaxis_key] = dict(
                                title=dict(text='', font=dict(color=color, size=10)),
                                tickfont=dict(color=color, size=9),
                                tickformat='.3g',
                                nticks=6,
                                range=[min_v, max_v],
                                gridcolor='rgba(255,255,255,0.07)',
                                linecolor=color,
                                linewidth=1,
                            )
                        else:
                            layout_super[yaxis_key] = dict(
                                title=dict(text='', font=dict(color=color, size=10)),
                                tickfont=dict(color=color, size=9),
                                tickformat='.3g',
                                nticks=6,
                                overlaying='y',
                                side='right',
                                autoshift=True,
                                range=[min_v, max_v],
                                showgrid=False,
                                linecolor=color,
                                linewidth=1,
                            )

                    fig_super.update_layout(**layout_super)
                    st.plotly_chart(fig_super, use_container_width=True)

                else:
                    st.info("👆 Seleccioná 2 o más variables arriba para ver la superposición con ejes independientes.")

        elif variables_seleccionadas and not col_datetime:
            st.error("Corregí la columna de tiempo antes de graficar.")
        else:
            st.info("👈 Seleccioná al menos una variable en el menú lateral.")
