# =============================================================================
# DASHBOARD.PY — Interface Gráfica de Monitoramento Industrial
# =============================================================================
# Função:
#   Exibe em tempo real os dados coletados pelos sensores de temperatura e
#   umidade, permitindo visualizar histórico, acionamentos e disparar ações
#   manuais (alarme e resfriamento) diretamente pela interface.
#
# Abas da interface:
#   1. Tempo Real    → gráficos ao vivo de temperatura e umidade
#   2. Histórico     → consulta por período com resumo estatístico por sensor
#   3. Acionamentos  → linha do tempo e lista de alarmes e resfriamentos
#
# Fluxo de comunicação:
#   cliente.py  →  HTTP GET /estado, /historico, /atuadores  →  server.py
#   cliente.py  →  HTTP POST /ativar/alarme ou /resfriamento →  server.py
# =============================================================================

import tkinter as tk
from tkinter import messagebox, ttk
import threading
import requests
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.dates as mdates
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from collections import defaultdict, deque
import queue
import time

# Endereço base do servidor central — altere se rodar fora do Docker
SERVER_URL = "http://localhost:5050"

# Períodos disponíveis no seletor da aba Tempo Real (rótulo → segundos)
PERIODOS = {
    "5s":   5,
    "10s":  10,
    "30s":  30,
    "1min": 60,
}

# =============================================================================
# PALETA DE CORES — tema escuro
# =============================================================================
BG_ROOT      = "#16161e"  # Fundo da janela principal
BG_PANEL     = "#1e1e2a"  # Painéis laterais e barras
BG_CARD      = "#252533"  # Cards e áreas de conteúdo
BG_HOVER     = "#2e2e3e"  # Hover de botões e checkboxes
BORDER       = "#35354a"  # Bordas e linhas de grade
TX_PRIMARY   = "#e2e2f0"  # Texto principal (branco suave)
TX_SECONDARY = "#8888aa"  # Texto secundário (cinza)
TX_MUTED     = "#55556a"  # Texto apagado (labels de seção)
AC_BLUE      = "#5b8dee"  # Azul de destaque (títulos de seção)
COR_DANGER   = "#e06c75"  # Vermelho — alarme / acima do limite
COR_OK       = "#61afaa"  # Verde-água — dentro do limite / online
COR_COLD     = "#56b6c2"  # Azul-claro — resfriamento / abaixo do limite
COR_WARN     = "#e5c07b"  # Amarelo — aviso

# Cores cicladas para diferenciar sensores nos gráficos
CORES_GRAF = [
    "#5b8dee", "#61afaa", "#e5c07b", "#c678dd",
    "#e06c75", "#56b6c2", "#98c379", "#d19a66",
]

# Limites de alarme por grandeza — espelho do que está em server.py
LIMITES = {
    "temperatura": {"max": 33, "min": 20, "unidade": "°C"},
    "umidade":     {"max": 85, "min": 45, "unidade": "%"},
}

# Kwargs compartilhados para todos os Radiobuttons — estilo discreto sem borda
# indicatoron=0 transforma o radio em botão toggle; relief+bd removem a borda azul do SO
_RB_KWARGS = dict(
    bg=BG_PANEL, fg=TX_SECONDARY,
    selectcolor=BG_CARD,
    activebackground=BG_HOVER,
    activeforeground=TX_PRIMARY,
    font=("Courier New", 9),
    indicatoron=0,
    relief="flat",
    bd=0,
    padx=8, pady=4,
    cursor="hand2",
)


# =============================================================================
# BUFFER CIRCULAR DE LEITURAS
# =============================================================================

# Armazena até MAXLEN leituras por sensor+tipo, descartando as mais antigas
class SensorBuffer:
    MAXLEN = 1200  # ~2 minutos a 10 leituras/s por sensor

    def __init__(self):
        # Chave: (sensor_id, tipo) → deque de (timestamp_float, valor)
        self._data: dict[tuple, deque] = defaultdict(
            lambda: deque(maxlen=self.MAXLEN)
        )
        # Rastreia o timestamp mais recente por chave para evitar duplicatas
        self._last_ts: dict[tuple, float] = {}

    def ingest(self, historico: list):
        # Percorre o histórico e adiciona apenas pontos mais recentes que o último visto
        for entry in historico:
            if not isinstance(entry, dict):
                continue
            sid  = entry.get("id", "?")
            tipo = entry.get("tipo", "")
            val  = entry.get("valor")
            ts_s = entry.get("horario", entry.get("timestamp", ""))
            if val is None or tipo not in ("temperatura", "umidade"):
                continue
            ts  = _parse_ts(ts_s).timestamp()
            key = (sid, tipo)
            # Só insere se for mais novo — evita reprocessar dados já plotados
            if ts > self._last_ts.get(key, 0):
                self._data[key].append((ts, float(val)))
                self._last_ts[key] = ts

    def get_filtrado(self, sid, tipo, janela_s: int) -> list:
        # Retorna pontos dentro da janela de tempo como lista de (datetime, valor)
        key = (sid, tipo)
        if key not in self._data:
            return []
        corte = datetime.now().timestamp() - janela_s
        return [
            (datetime.fromtimestamp(t), v)
            for t, v in self._data[key]
            if t >= corte
        ]

    def sensores(self) -> set:
        # Retorna os IDs únicos de sensores que já enviaram dados
        return {k[0] for k in self._data}


# Tenta parsear timestamp nos dois formatos usados pelo servidor
def _parse_ts(ts_str: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(ts_str, fmt)
        except (ValueError, TypeError):
            pass
    return datetime.now()  # fallback: usa o instante atual se o formato for inválido


# =============================================================================
# FUNÇÕES DE I/O — chamadas na thread de background
# =============================================================================

# Busca o estado atual de todos os sensores (último valor de cada um)
def get_estado():
    try:
        r = requests.get(f"{SERVER_URL}/estado", timeout=2)
        d = r.json()
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# Busca o histórico de leituras; parâmetros são ignorados pelo server atual
def get_historico(segundos=30):
    try:
        r = requests.get(
            f"{SERVER_URL}/historico?segundos={segundos}&limite=1200",
            timeout=2
        )
        d = r.json()
        return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []
    except Exception:
        return []


# Busca todos os acionamentos registrados (alarmes e resfriamentos)
def get_atuadores():
    try:
        r = requests.get(f"{SERVER_URL}/atuadores", timeout=2)
        d = r.json()
        return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []
    except Exception:
        return []


# Busca o histórico completo sem filtro de janela — usado na aba Histórico
def get_historico_completo():
    try:
        r = requests.get(f"{SERVER_URL}/historico", timeout=4)
        d = r.json()
        return [e for e in d if isinstance(e, dict)] if isinstance(d, list) else []
    except Exception:
        return []


# Dispara alarme ou resfriamento manualmente via POST
def _requisitar_ativar(acao: str) -> tuple[bool, str]:
    try:
        r = requests.post(
            f"{SERVER_URL}/ativar/{acao}",
            json={"sensor": "manual", "valor": 0},
            timeout=3
        )
        return True, r.json().get("acao", acao)
    except Exception as e:
        return False, str(e)


# Limpa os dados do servidor ao fechar a janela (evita persistência entre sessões)
def limpar_dados_servidor():
    try:
        requests.post(f"{SERVER_URL}/limpar", json={}, timeout=3)
    except Exception:
        pass


# =============================================================================
# ESTILO DOS GRÁFICOS MATPLOTLIB
# =============================================================================

# Aplica o tema escuro a um eixo: fundo, bordas, ticks e grade
def _estilo_ax(ax, ylabel="", show_grid=True):
    ax.set_facecolor(BG_CARD)
    for spine in ax.spines.values():
        spine.set_edgecolor(BORDER)
        spine.set_linewidth(0.6)
    ax.tick_params(colors=TX_SECONDARY, labelsize=8, length=3, pad=4)
    ax.set_ylabel(ylabel, color=TX_SECONDARY, fontsize=8, labelpad=8)
    if show_grid:
        ax.grid(axis="y", color=BORDER, linewidth=0.4, linestyle="--", alpha=0.6)
        ax.grid(axis="x", color=BORDER, linewidth=0.2, linestyle=":", alpha=0.3)
    ax.set_axisbelow(True)  # grade fica atrás das linhas do gráfico


# Formata o eixo X com intervalo e formato adequados à janela de tempo selecionada
def _formatar_eixo_x(ax, janela_s: int):
    if janela_s <= 30:
        fmt = mdates.DateFormatter("%H:%M:%S")
        loc = mdates.SecondLocator(interval=max(1, janela_s // 5))
    elif janela_s <= 120:
        fmt = mdates.DateFormatter("%H:%M:%S")
        loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
    else:
        fmt = mdates.DateFormatter("%H:%M")
        loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
    ax.xaxis.set_major_formatter(fmt)
    ax.xaxis.set_major_locator(loc)
    plt.setp(ax.get_xticklabels(),
             rotation=0, ha="center", fontsize=7.5, color=TX_SECONDARY)


# =============================================================================
# CLASSE PRINCIPAL — janela Tkinter
# =============================================================================

class App(tk.Tk):
    POLL_MS       = 500   # Intervalo entre disparos do worker de I/O (ms)
    DRAW_INTERVAL = 0.5   # Intervalo mínimo entre redesenhos dos gráficos (s)

    def __init__(self):
        super().__init__()
        self.title("Monitoramento Industrial")
        self.geometry("1320x800")
        self.minsize(1100, 680)
        self.configure(bg=BG_ROOT)

        # Dicionários de controle de sensores e estado da UI
        self._sensores_vars       = {}   # sensor_id → BooleanVar (checkbox ativo?)
        self._sensores_conhecidos = set()
        self._sensores_status     = {}   # sensor_id → widgets de status

        self._periodo_var = tk.StringVar(value="30s")

        self._worker_rodando  = False   # impede múltiplas threads de I/O simultâneas
        self._contador_poll   = 0       # conta ciclos para buscar atuadores com menor frequência
        self._ultimo_draw     = 0.0     # timestamp do último redesenho (controla DRAW_INTERVAL)
        self._cache_atuadores: list = []

        # Fila thread-safe: thread de I/O produz, thread principal consome
        self._ui_queue: queue.Queue = queue.Queue()
        self._buffer = SensorBuffer()

        self._build_ui()
        self._processar_fila()   # inicia o loop de consumo da fila
        self._disparar_worker()  # inicia o loop de busca de dados

        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)

    def _ao_fechar(self):
        # Limpa dados no servidor em background antes de destruir a janela
        threading.Thread(target=limpar_dados_servidor, daemon=True).start()
        self.after(400, self.destroy)

    def _ativar_manual(self, acao: str):
        # Chamado pelo botão — roda na thread principal, resultado vai para a fila
        ok, msg = _requisitar_ativar(acao)
        self._ui_queue.put({"tipo": "msg_ativar", "ok": ok, "msg": msg, "acao": acao})

    # =========================================================================
    # CONSTRUÇÃO DA INTERFACE
    # =========================================================================

    def _build_ui(self):
        # Barra superior com título e indicador de conexão
        header = tk.Frame(self, bg=BG_PANEL, height=48)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header, text="MONITORAMENTO INDUSTRIAL",
            font=("Courier New", 13, "bold"),
            bg=BG_PANEL, fg=TX_PRIMARY
        ).pack(side="left", padx=20, pady=12)
        self.lbl_conexao = tk.Label(
            header, text="● OFFLINE",
            font=("Courier New", 9), bg=BG_PANEL, fg=COR_DANGER
        )
        self.lbl_conexao.pack(side="right", padx=20)

        # Barra inferior com informações de última atualização e contagem de registros
        self.status_bar = tk.Label(
            self, text="Conectando...",
            bg=BG_PANEL, fg=TX_MUTED, anchor="w",
            font=("Courier New", 8)
        )
        self.status_bar.pack(fill="x", side="bottom")

        # Estilo do Notebook (abas) para combinar com o tema escuro
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Dark.TNotebook", background=BG_ROOT, borderwidth=0)
        style.configure("Dark.TNotebook.Tab",
                        background=BG_PANEL, foreground=TX_SECONDARY,
                        font=("Courier New", 9, "bold"), padding=[16, 6])
        style.map("Dark.TNotebook.Tab",
                  background=[("selected", BG_CARD)],
                  foreground=[("selected", TX_PRIMARY)])

        self.notebook = ttk.Notebook(self, style="Dark.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        # Criação das três abas
        self.aba_live = tk.Frame(self.notebook, bg=BG_ROOT)
        self.notebook.add(self.aba_live, text="  TEMPO REAL  ")
        self.aba_hist = tk.Frame(self.notebook, bg=BG_ROOT)
        self.notebook.add(self.aba_hist, text="  HISTÓRICO  ")
        self.aba_atu = tk.Frame(self.notebook, bg=BG_ROOT)
        self.notebook.add(self.aba_atu, text="  ACIONAMENTOS  ")

        self._build_live(self.aba_live)
        self._build_historico(self.aba_hist)
        self._build_atuadores_aba(self.aba_atu)
        # Atualiza o conteúdo correto ao trocar de aba
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

    # Label de seção azul usada em vários painéis
    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=("Courier New", 8, "bold"),
                 bg=parent.cget("bg"), fg=AC_BLUE).pack(anchor="w", padx=12, pady=(10, 4))

    # Linha divisória horizontal entre seções do painel
    def _divider(self, parent):
        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=8, pady=4)

    # =========================================================================
    # ABA 1 — TEMPO REAL
    # =========================================================================

    def _build_live(self, parent):
        # Layout em três colunas: painel esquerdo | gráficos | painel direito
        body = tk.Frame(parent, bg=BG_ROOT)
        body.pack(fill="both", expand=True)
        self._build_left(body)
        self._build_center(body)
        self._build_right(body)

    def _build_left(self, parent):
        # Painel esquerdo: status dos sensores, seletor de período, checkboxes e ações manuais
        left = tk.Frame(parent, bg=BG_PANEL, width=200)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self._section_label(left, "STATUS")
        self.status_frame = tk.Frame(left, bg=BG_PANEL)
        self.status_frame.pack(fill="x", padx=10)
        self._status_widgets = {}

        self._divider(left)
        self._section_label(left, "PERÍODO")
        pf = tk.Frame(left, bg=BG_PANEL)
        pf.pack(fill="x", padx=10, pady=(0, 8))
        for label, val in [("5 seg", "5s"), ("10 seg", "10s"),
                            ("30 seg", "30s"), ("1 min", "1min")]:
            tk.Radiobutton(
                pf, text=label, variable=self._periodo_var, value=val,
                command=self._redesenhar,
                **_RB_KWARGS
            ).pack(fill="x", pady=1)

        self._divider(left)
        self._section_label(left, "SENSORES")
        # Checkboxes de sensores são criados dinamicamente em _registrar_sensores
        self.check_frame = tk.Frame(left, bg=BG_PANEL)
        self.check_frame.pack(fill="x", padx=10)

        self._divider(left)
        self._section_label(left, "AÇÕES MANUAIS")
        af = tk.Frame(left, bg=BG_PANEL)
        af.pack(fill="x", padx=10, pady=4)
        # Botão de alarme: vermelho, chama _ativar_manual em thread separada para não travar a UI
        tk.Button(
            af, text="⚠  DISPARAR ALARME",
            font=("Courier New", 9, "bold"), bg=COR_DANGER, fg="#ffffff",
            relief="flat", padx=10, pady=8, cursor="hand2",
            activebackground="#c0414b", activeforeground="#ffffff",
            command=lambda: threading.Thread(
                target=self._ativar_manual, args=("alarme",), daemon=True).start()
        ).pack(fill="x", pady=(0, 6))
        # Botão de resfriamento: borda azul fria, mesma lógica de thread separada
        tk.Button(
            af, text="❄  RESFRIAMENTO",
            font=("Courier New", 9), bg=BG_CARD, fg=COR_COLD,
            relief="flat", padx=10, pady=7, cursor="hand2",
            activebackground=BG_HOVER, activeforeground=COR_COLD,
            highlightthickness=1, highlightbackground=COR_COLD,
            command=lambda: threading.Thread(
                target=self._ativar_manual, args=("resfriamento",), daemon=True).start()
        ).pack(fill="x")

    def _build_center(self, parent):
        # Área central com dois subgráficos empilhados: temperatura (cima) e umidade (baixo)
        center = tk.Frame(parent, bg=BG_ROOT)
        center.pack(side="left", fill="both", expand=True, padx=1)
        tk.Label(center, text="HISTÓRICO EM TEMPO REAL",
                 font=("Courier New", 9, "bold"),
                 bg=BG_ROOT, fg=TX_MUTED).pack(anchor="w", padx=16, pady=(10, 4))

        self.fig = plt.Figure(figsize=(6, 5.5), facecolor=BG_ROOT)
        self.fig.subplots_adjust(left=0.09, right=0.93, top=0.96, bottom=0.12, hspace=0.55)
        self.ax_temp = self.fig.add_subplot(2, 1, 1)  # Gráfico de temperatura
        self.ax_umid = self.fig.add_subplot(2, 1, 2)  # Gráfico de umidade
        for ax in (self.ax_temp, self.ax_umid):
            _estilo_ax(ax)

        # Canvas do matplotlib embutido no Tkinter
        self.canvas = FigureCanvasTkAgg(self.fig, master=center)
        self.canvas.get_tk_widget().configure(bg=BG_ROOT, highlightthickness=0)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=(0, 8))

    def _build_right(self, parent):
        # Painel direito: contadores de acionamentos, gráfico de barras por sensor e último evento
        right = tk.Frame(parent, bg=BG_PANEL, width=220)
        right.pack(side="left", fill="y")
        right.pack_propagate(False)

        self._section_label(right, "ACIONAMENTOS")
        cards = tk.Frame(right, bg=BG_PANEL)
        cards.pack(fill="x", padx=10, pady=(0, 4))

        # Card de contagem de alarmes
        ca = tk.Frame(cards, bg=BG_CARD, pady=8, padx=6)
        ca.pack(side="left", fill="both", expand=True, padx=3, pady=3)
        tk.Label(ca, text="ALARMES", font=("Courier New", 7), bg=BG_CARD, fg=TX_MUTED).pack()
        self.lbl_alarme = tk.Label(ca, text="0", font=("Courier New", 22, "bold"),
                                    bg=BG_CARD, fg=COR_DANGER)
        self.lbl_alarme.pack()

        # Card de contagem de resfriamentos
        cr = tk.Frame(cards, bg=BG_CARD, pady=8, padx=6)
        cr.pack(side="left", fill="both", expand=True, padx=3, pady=3)
        tk.Label(cr, text="RESFR.", font=("Courier New", 7), bg=BG_CARD, fg=TX_MUTED).pack()
        self.lbl_resf = tk.Label(cr, text="0", font=("Courier New", 22, "bold"),
                                  bg=BG_CARD, fg=COR_COLD)
        self.lbl_resf.pack()

        self._divider(right)
        self._section_label(right, "POR SENSOR")
        # Gráfico de barras agrupadas: alarmes vs resfriamentos por sensor
        self.fig2 = plt.Figure(figsize=(2.8, 2.8), facecolor=BG_PANEL)
        self.fig2.subplots_adjust(left=0.12, right=0.97, top=0.95, bottom=0.22)
        self.ax_atu = self.fig2.add_subplot(1, 1, 1)
        _estilo_ax(self.ax_atu, show_grid=False)
        self.canvas2 = FigureCanvasTkAgg(self.fig2, master=right)
        self.canvas2.get_tk_widget().configure(bg=BG_PANEL, highlightthickness=0)
        self.canvas2.get_tk_widget().pack(fill="both", expand=True, padx=8)

        self._divider(right)
        self._section_label(right, "ÚLTIMO ACIONAMENTO")
        self.lbl_ultimo = tk.Label(right, text="—", font=("Courier New", 8),
                                    bg=BG_PANEL, fg=TX_SECONDARY,
                                    wraplength=200, justify="left")
        self.lbl_ultimo.pack(anchor="w", padx=12, pady=(0, 8))

    # =========================================================================
    # ABA 2 — HISTÓRICO
    # =========================================================================

    def _build_historico(self, parent):
        # Barra de ferramentas: seletor de tipo (temperatura/umidade) e período
        toolbar = tk.Frame(parent, bg=BG_PANEL, height=44)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Label(toolbar, text="TIPO:", font=("Courier New", 8),
                 bg=BG_PANEL, fg=TX_SECONDARY).pack(side="left", padx=(12, 4), pady=10)
        self._hist_tipo_var = tk.StringVar(value="temperatura")
        for txt, val in [("Temperatura", "temperatura"), ("Umidade", "umidade")]:
            tk.Radiobutton(
                toolbar, text=txt, variable=self._hist_tipo_var, value=val,
                command=self._atualizar_historico,
                **_RB_KWARGS
            ).pack(side="left", padx=2, pady=8)

        tk.Label(toolbar, text="PERÍODO:", font=("Courier New", 8),
                 bg=BG_PANEL, fg=TX_SECONDARY).pack(side="left", padx=(20, 4))

        self._hist_periodo_var = tk.StringVar(value="3min")
        for txt, val in [("1 min", "1min"), ("3 min", "3min"),
                          ("5 min", "5min"), ("10 min", "10min"), ("Tudo", "tudo")]:
            tk.Radiobutton(
                toolbar, text=txt, variable=self._hist_periodo_var, value=val,
                command=self._atualizar_historico,
                **_RB_KWARGS
            ).pack(side="left", padx=2, pady=8)

        tk.Button(toolbar, text="↺ ATUALIZAR", font=("Courier New", 8, "bold"),
                  bg=BG_CARD, fg=AC_BLUE, relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=BG_HOVER, activeforeground=AC_BLUE,
                  command=self._atualizar_historico).pack(side="right", padx=12, pady=8)

        # Gráfico principal da aba de histórico
        self.fig_hist = plt.Figure(figsize=(8, 4.5), facecolor=BG_ROOT)
        self.fig_hist.subplots_adjust(left=0.07, right=0.97, top=0.93, bottom=0.12)
        self.ax_hist = self.fig_hist.add_subplot(1, 1, 1)
        _estilo_ax(self.ax_hist)
        self.canvas_hist = FigureCanvasTkAgg(self.fig_hist, master=parent)
        self.canvas_hist.get_tk_widget().configure(bg=BG_ROOT, highlightthickness=0)
        self.canvas_hist.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=8)

        # Faixa inferior com cards de resumo estatístico por sensor
        resumo_frame = tk.Frame(parent, bg=BG_PANEL, height=90)
        resumo_frame.pack(fill="x", padx=12, pady=(0, 8))
        resumo_frame.pack_propagate(False)
        self._resumo_frame   = resumo_frame
        self._resumo_widgets = {}

    def _atualizar_historico(self):
        tipo    = self._hist_tipo_var.get()
        periodo = self._hist_periodo_var.get()
        dados   = get_historico_completo()

        # Filtra por período quando não é "tudo"
        if periodo != "tudo":
            minutos = {"1min": 1, "3min": 3, "5min": 5, "10min": 10}.get(periodo, 3)
            corte   = datetime.now() - timedelta(minutes=minutos)
            filtrados = []
            for e in dados:
                try:
                    ts_campo = e.get("horario", e.get("timestamp", ""))
                    if _parse_ts(ts_campo) >= corte:
                        filtrados.append(e)
                except Exception:
                    pass
            dados = filtrados

        # Agrupa pontos por sensor para plotar uma linha por sensor
        por_sensor = defaultdict(list)
        for e in dados:
            if e.get("tipo") == tipo:
                try:
                    ts_campo = e.get("horario", e.get("timestamp", ""))
                    ts  = _parse_ts(ts_campo)
                    val = float(e["valor"])
                    por_sensor[e["id"]].append((ts, val))
                except Exception:
                    pass

        self.ax_hist.clear()
        _estilo_ax(self.ax_hist,
                   ylabel="Temperatura (°C)" if tipo == "temperatura" else "Umidade (%)")
        cfg     = LIMITES[tipo]
        lim_max = cfg["max"]
        lim_min = cfg["min"]
        unidade = cfg["unidade"]

        # Linhas tracejadas indicando os limites de alarme
        self.ax_hist.axhline(lim_max, color=COR_DANGER, linewidth=0.8, linestyle="--", alpha=0.5)
        self.ax_hist.axhline(lim_min, color=COR_COLD,   linewidth=0.8, linestyle="--", alpha=0.5)
        self.ax_hist.annotate(f"max {lim_max}{unidade}",
                              xy=(0.99, lim_max), xycoords=("axes fraction", "data"),
                              xytext=(-4, 3), textcoords="offset points",
                              color=COR_DANGER, fontsize=6.5, ha="right", alpha=0.8)
        self.ax_hist.annotate(f"min {lim_min}{unidade}",
                              xy=(0.99, lim_min), xycoords=("axes fraction", "data"),
                              xytext=(-4, -9), textcoords="offset points",
                              color=COR_COLD, fontsize=6.5, ha="right", alpha=0.8)

        # Remove cards de resumo anteriores antes de recriá-los
        for w in self._resumo_frame.winfo_children():
            w.destroy()
        self._resumo_widgets = {}

        if not por_sensor:
            self.ax_hist.text(0.5, 0.5, "sem dados no período",
                              transform=self.ax_hist.transAxes,
                              ha="center", va="center", color=TX_MUTED, fontsize=11)
            self.fig_hist.tight_layout(pad=1.2)
            self.canvas_hist.draw_idle()
            return

        all_vals = []
        for i, (sid, pontos) in enumerate(sorted(por_sensor.items())):
            cor      = CORES_GRAF[i % len(CORES_GRAF)]
            nome_cur = sid.replace("sensor_", "").replace("_", " ")
            ts_list  = [p[0] for p in pontos]
            v_list   = [p[1] for p in pontos]
            all_vals.extend(v_list)

            self.ax_hist.plot(ts_list, v_list, color=cor, linewidth=1.4, alpha=0.9, label=nome_cur)
            self.ax_hist.fill_between(ts_list, v_list, alpha=0.04, color=cor)

            # Estatísticas para o card de resumo
            media = sum(v_list) / len(v_list)
            maxi  = max(v_list)
            mini  = min(v_list)
            fora  = sum(1 for v in v_list if v > lim_max or v < lim_min)

            # Card de resumo: média, máximo, mínimo e contagem de leituras fora do limite
            card = tk.Frame(self._resumo_frame, bg=BG_CARD, padx=10, pady=6)
            card.pack(side="left", fill="y", padx=4, pady=6)
            tk.Label(card, text="●", font=("Courier New", 10),
                     bg=BG_CARD, fg=cor).pack(side="left", padx=(0, 6))
            info = tk.Frame(card, bg=BG_CARD)
            info.pack(side="left")
            tk.Label(info, text=nome_cur.upper(), font=("Courier New", 7, "bold"),
                     bg=BG_CARD, fg=TX_MUTED).grid(row=0, column=0, columnspan=4, sticky="w")
            for col, (lbl, val, cor_val) in enumerate([
                ("méd", f"{media:.1f}{unidade}", TX_SECONDARY),
                ("máx", f"{maxi:.1f}{unidade}",  COR_DANGER if maxi > lim_max else TX_SECONDARY),
                ("mín", f"{mini:.1f}{unidade}",  COR_COLD   if mini < lim_min else TX_SECONDARY),
                ("⚠",  str(fora),               COR_DANGER if fora > 0       else COR_OK),
            ]):
                tk.Label(info, text=lbl, font=("Courier New", 6),
                         bg=BG_CARD, fg=TX_MUTED).grid(row=1, column=col, padx=5)
                tk.Label(info, text=val, font=("Courier New", 8, "bold"),
                         bg=BG_CARD, fg=cor_val).grid(row=2, column=col, padx=5)

        # Formato do eixo X varia conforme o período selecionado
        if periodo in ("1min", "3min", "5min"):
            self.ax_hist.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        else:
            self.ax_hist.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        self.ax_hist.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.setp(self.ax_hist.get_xticklabels(),
                 rotation=0, ha="center", fontsize=7.5, color=TX_SECONDARY)

        # Ajusta escala Y para incluir todos os valores e os limites com margem
        if all_vals:
            self.ax_hist.set_ylim(min(min(all_vals), lim_min) - 3,
                                  max(max(all_vals), lim_max) + 4)

        self.ax_hist.legend(
            facecolor=BG_PANEL, labelcolor=TX_SECONDARY, fontsize=7, loc="upper left",
            framealpha=0.85, edgecolor=BORDER, ncol=min(len(por_sensor), 4),
            handlelength=1.2, handletextpad=0.5, borderpad=0.5, columnspacing=0.8
        )
        self.fig_hist.tight_layout(pad=1.2)
        self.canvas_hist.draw_idle()

    # =========================================================================
    # ABA 3 — ACIONAMENTOS
    # =========================================================================

    def _build_atuadores_aba(self, parent):
        # Barra de ferramentas: filtro por tipo de ação e botão de atualizar
        toolbar = tk.Frame(parent, bg=BG_PANEL, height=44)
        toolbar.pack(fill="x")
        toolbar.pack_propagate(False)

        tk.Button(toolbar, text="↺ ATUALIZAR", font=("Courier New", 8, "bold"),
                  bg=BG_CARD, fg=AC_BLUE, relief="flat", padx=10, pady=4, cursor="hand2",
                  activebackground=BG_HOVER, activeforeground=AC_BLUE,
                  command=self._atualizar_aba_atuadores).pack(side="right", padx=12, pady=8)

        tk.Label(toolbar, text="FILTRAR:", font=("Courier New", 8),
                 bg=BG_PANEL, fg=TX_SECONDARY).pack(side="left", padx=(12, 4), pady=10)
        self._atu_filtro_var = tk.StringVar(value="TODOS")
        for txt, val in [("Todos", "TODOS"), ("Alarme", "ALARME"), ("Resfr.", "RESFRIAMENTO")]:
            tk.Radiobutton(
                toolbar, text=txt, variable=self._atu_filtro_var, value=val,
                command=self._atualizar_aba_atuadores,
                **_RB_KWARGS
            ).pack(side="left", padx=2, pady=8)

        # Layout: gráfico de linha do tempo (esquerda) + lista de eventos (direita)
        body = tk.Frame(parent, bg=BG_ROOT)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        left_f = tk.Frame(body, bg=BG_ROOT)
        left_f.pack(side="left", fill="both", expand=True)
        tk.Label(left_f, text="LINHA DO TEMPO", font=("Courier New", 8, "bold"),
                 bg=BG_ROOT, fg=AC_BLUE).pack(anchor="w", pady=(0, 4))

        # Gráfico de dispersão: cada ponto = um acionamento no tempo
        self.fig_atu_line = plt.Figure(figsize=(5, 3.5), facecolor=BG_ROOT)
        self.fig_atu_line.subplots_adjust(left=0.10, right=0.97, top=0.92, bottom=0.18)
        self.ax_atu_line = self.fig_atu_line.add_subplot(1, 1, 1)
        _estilo_ax(self.ax_atu_line, ylabel="Valor", show_grid=True)
        self.canvas_atu_line = FigureCanvasTkAgg(self.fig_atu_line, master=left_f)
        self.canvas_atu_line.get_tk_widget().configure(bg=BG_ROOT, highlightthickness=0)
        self.canvas_atu_line.get_tk_widget().pack(fill="both", expand=True)

        right_f = tk.Frame(body, bg=BG_PANEL, width=340)
        right_f.pack(side="left", fill="y", padx=(10, 0))
        right_f.pack_propagate(False)
        tk.Label(right_f, text="EVENTOS RECENTES", font=("Courier New", 8, "bold"),
                 bg=BG_PANEL, fg=AC_BLUE).pack(anchor="w", padx=10, pady=(8, 4))

        # Listbox com scrollbar para eventos recentes
        list_frame = tk.Frame(right_f, bg=BG_PANEL)
        list_frame.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        scrollbar = tk.Scrollbar(list_frame, bg=BG_PANEL, troughcolor=BG_CARD, relief="flat")
        scrollbar.pack(side="right", fill="y")
        self.listbox_atu = tk.Listbox(
            list_frame, bg=BG_CARD, fg=TX_SECONDARY, font=("Courier New", 8),
            selectbackground=BG_HOVER, selectforeground=TX_PRIMARY,
            relief="flat", borderwidth=0, highlightthickness=0,
            yscrollcommand=scrollbar.set, activestyle="none"
        )
        self.listbox_atu.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox_atu.yview)

    def _atualizar_aba_atuadores(self):
        atuadores = get_atuadores()
        filtro    = self._atu_filtro_var.get()
        if filtro != "TODOS":
            atuadores = [a for a in atuadores if a.get("acao") == filtro]

        self.ax_atu_line.clear()
        _estilo_ax(self.ax_atu_line, ylabel="Valor registrado", show_grid=True)

        # Separa os acionamentos por tipo para plotar com cores diferentes
        alarmes = [(a, a.get("valor", 0)) for a in atuadores if a.get("acao") == "ALARME"]
        resfrs  = [(a, a.get("valor", 0)) for a in atuadores if a.get("acao") == "RESFRIAMENTO"]

        def parse_ts(a):
            ts_campo = a[0].get("timestamp", a[0].get("horario", ""))
            return _parse_ts(ts_campo)

        # Círculos vermelhos para alarmes, triângulos azuis para resfriamentos
        if alarmes:
            self.ax_atu_line.scatter(
                [parse_ts(a) for a in alarmes], [a[1] for a in alarmes],
                color=COR_DANGER, s=18, zorder=4, label="Alarme", alpha=0.85)
        if resfrs:
            self.ax_atu_line.scatter(
                [parse_ts(r) for r in resfrs], [r[1] for r in resfrs],
                color=COR_COLD, s=18, zorder=4, label="Resfr.", alpha=0.85, marker="^")

        if alarmes or resfrs:
            self.ax_atu_line.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
            self.ax_atu_line.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.setp(self.ax_atu_line.get_xticklabels(),
                     rotation=0, ha="center", fontsize=7.5, color=TX_SECONDARY)
            self.ax_atu_line.legend(facecolor=BG_PANEL, labelcolor=TX_SECONDARY,
                                     fontsize=7, framealpha=0.85, edgecolor=BORDER)
        else:
            self.ax_atu_line.text(0.5, 0.5, "sem acionamentos",
                                  transform=self.ax_atu_line.transAxes,
                                  ha="center", va="center", color=TX_MUTED, fontsize=10)

        self.fig_atu_line.tight_layout(pad=1.0)
        self.canvas_atu_line.draw_idle()

        # Preenche a listbox com os 200 eventos mais recentes (mais novo no topo)
        self.listbox_atu.delete(0, tk.END)
        for a in reversed(atuadores[-200:]):
            acao  = a.get("acao", "?")
            nome  = a.get("nome_sensor", "?").replace("sensor_", "")
            valor = a.get("valor", "?")
            ts    = a.get("timestamp", a.get("horario", ""))
            icone = "⚠" if acao == "ALARME" else "❄"
            self.listbox_atu.insert(0, f"{icone} {ts[-15:]}  {nome:<14} {valor}")
        # Colore cada linha conforme o tipo de acionamento
        for i in range(self.listbox_atu.size()):
            item = self.listbox_atu.get(i)
            self.listbox_atu.itemconfig(i, fg=COR_DANGER if item.startswith("⚠") else COR_COLD)

    # =========================================================================
    # GERENCIAMENTO DE STATUS DOS SENSORES
    # =========================================================================

    def _registrar_sensores(self, estado):
        # Cria checkbox e widget de status apenas para sensores novos (não recria os existentes)
        if not isinstance(estado, dict):
            return
        novos = set(estado.keys()) - self._sensores_conhecidos
        if not novos:
            return
        for sid in sorted(novos):
            var = tk.BooleanVar(value=True)
            self._sensores_vars[sid] = var
            idx = len(self._sensores_conhecidos)
            cor = CORES_GRAF[idx % len(CORES_GRAF)]

            # Checkbox na seção "SENSORES" do painel esquerdo
            row = tk.Frame(self.check_frame, bg=BG_PANEL)
            row.pack(anchor="w", pady=1, fill="x")
            tk.Label(row, text="●", font=("Courier New", 10),
                     bg=BG_PANEL, fg=cor, width=2).pack(side="left")
            nome_curto = sid.replace("sensor_", "").replace("_", " ")
            tk.Checkbutton(row, text=nome_curto, variable=var,
                           bg=BG_PANEL, fg=TX_SECONDARY, selectcolor=BG_CARD,
                           activebackground=BG_PANEL, activeforeground=TX_PRIMARY,
                           font=("Courier New", 8), command=self._redesenhar).pack(side="left")

            # Card de status na seção "STATUS" com ícone e valor atual
            row_st = tk.Frame(self.status_frame, bg=BG_CARD, pady=3, padx=8)
            row_st.pack(fill="x", pady=1)
            lbl_icone = tk.Label(row_st, text="●", bg=BG_CARD,
                                  fg=TX_SECONDARY, font=("Courier New", 8), width=2)
            lbl_icone.pack(side="left")
            tk.Label(row_st, text=nome_curto, bg=BG_CARD,
                     fg=TX_SECONDARY, font=("Courier New", 8)).pack(side="left")
            lbl_val = tk.Label(row_st, text="—", bg=BG_CARD,
                                fg=TX_SECONDARY, font=("Courier New", 9, "bold"))
            lbl_val.pack(side="right")
            self._status_widgets[sid] = {"icone": lbl_icone, "valor": lbl_val}
            self._sensores_conhecidos.add(sid)

    def _atualizar_status(self, estado):
        # Atualiza ícone e cor de cada sensor conforme o valor está dentro ou fora dos limites
        online = bool(estado)
        self.lbl_conexao.config(text="● ONLINE" if online else "● OFFLINE",
                                fg=COR_OK if online else COR_DANGER)
        if not isinstance(estado, dict):
            return
        lims_map = {"temperatura": (20, 33), "umidade": (45, 85)}
        for sid, info in estado.items():
            if sid not in self._status_widgets or not isinstance(info, dict):
                continue
            tipo    = info.get("tipo", "?")
            valor   = info.get("valor", "?")
            unidade = "°C" if tipo == "temperatura" else "%"
            lim     = lims_map.get(tipo, (None, None))
            try:
                if lim[1] and valor > lim[1]:
                    cor, icone = COR_DANGER, "▲"  # Acima do limite
                elif lim[0] and valor < lim[0]:
                    cor, icone = COR_COLD,   "▼"  # Abaixo do limite
                else:
                    cor, icone = COR_OK,     "●"  # Dentro do limite
            except TypeError:
                cor, icone = TX_SECONDARY, "●"
            w = self._status_widgets[sid]
            w["icone"].config(text=icone, fg=cor)
            w["valor"].config(text=f"{valor}{unidade}", fg=cor)

    # =========================================================================
    # ATUALIZAÇÃO DO PAINEL DE ATUADORES (coluna direita da aba Tempo Real)
    # =========================================================================

    def _atualizar_atuadores(self, atuadores):
        if not isinstance(atuadores, list):
            atuadores = []
        total_a = sum(1 for a in atuadores if isinstance(a, dict) and a.get("acao") == "ALARME")
        total_r = sum(1 for a in atuadores if isinstance(a, dict) and a.get("acao") == "RESFRIAMENTO")
        self.lbl_alarme.config(text=str(total_a))
        self.lbl_resf.config(text=str(total_r))

        # Exibe o último acionamento com cor conforme o tipo
        if atuadores:
            ult = atuadores[-1]
            if isinstance(ult, dict):
                acao = ult.get("acao", "?")
                nome = ult.get("nome_sensor", "?").replace("sensor_", "")[:16]
                ts   = ult.get("timestamp", ult.get("horario", ""))
                self.lbl_ultimo.config(text=f"{acao}\n{nome}\n{ts[-19:]}",
                                       fg=COR_DANGER if acao == "ALARME" else COR_COLD)

        # Conta alarmes e resfriamentos por sensor para o gráfico de barras
        contagem = defaultdict(lambda: {"ALARME": 0, "RESFRIAMENTO": 0})
        for a in atuadores:
            if not isinstance(a, dict):
                continue
            sid  = a.get("nome_sensor", "?")
            acao = a.get("acao", "?")
            if acao in ("ALARME", "RESFRIAMENTO"):
                contagem[sid][acao] += 1

        self.ax_atu.clear()
        _estilo_ax(self.ax_atu, show_grid=False)

        if contagem:
            sensores = list(contagem.keys())
            alarmes  = [contagem[s]["ALARME"]       for s in sensores]
            resfr    = [contagem[s]["RESFRIAMENTO"] for s in sensores]
            x        = range(len(sensores))
            w        = 0.38  # Largura de cada barra

            # Barras lado a lado: vermelho (alarme) e azul (resfriamento)
            bars_a = self.ax_atu.bar([i - w/2 for i in x], alarmes, w,
                                      color=COR_DANGER, label="Alarme", zorder=3, linewidth=0)
            bars_r = self.ax_atu.bar([i + w/2 for i in x], resfr, w,
                                      color=COR_COLD, label="Resfr.", zorder=3, linewidth=0)
            # Rótulo numérico em cima de cada barra com valor > 0
            for bar in list(bars_a) + list(bars_r):
                h = bar.get_height()
                if h > 0:
                    self.ax_atu.text(bar.get_x() + bar.get_width() / 2,
                                     h + max(1, h * 0.03), str(int(h)),
                                     ha="center", va="bottom", color=TX_SECONDARY, fontsize=6.5)
            # Abrevia nomes: "sensor_temp_1" → "T1", "sensor_umidade_1" → "U1"
            nomes = [s.replace("sensor_", "").replace("temp_", "T").replace("umidade_", "U")
                     for s in sensores]
            self.ax_atu.set_xticks(list(x))
            self.ax_atu.set_xticklabels(nomes, fontsize=7, color=TX_SECONDARY)
            self.ax_atu.legend(facecolor=BG_CARD, labelcolor=TX_SECONDARY,
                                fontsize=6.5, framealpha=0.9, edgecolor=BORDER, loc="upper right")
            # Garante que o eixo Y só exibe valores inteiros
            self.ax_atu.yaxis.set_major_locator(ticker.MaxNLocator(integer=True, nbins=4))
        else:
            self.ax_atu.text(0.5, 0.5, "sem acionamentos", transform=self.ax_atu.transAxes,
                             ha="center", color=TX_MUTED, fontsize=8)
        self.fig2.tight_layout(pad=0.8)
        self.canvas2.draw_idle()

    # =========================================================================
    # FILTRAGEM E PLOTAGEM DOS GRÁFICOS EM TEMPO REAL
    # =========================================================================

    def _agregar(self, pontos: list, max_pts: int = 120) -> list:
        # Reduz a quantidade de pontos por média agrupada quando há mais que max_pts
        # Isso mantém o gráfico fluido mesmo com muitas leituras acumuladas
        if len(pontos) <= max_pts:
            return pontos
        fator = len(pontos) // max_pts
        res   = []
        for i in range(0, len(pontos) - fator + 1, fator):
            grupo = pontos[i:i + fator]
            ts    = grupo[len(grupo) // 2][0]  # timestamp do ponto central do grupo
            media = round(sum(p[1] for p in grupo) / len(grupo), 2)
            res.append((ts, media))
        return res

    def _filtrar(self):
        # Retorna dicionários {sensor_id: [(datetime, valor)]} para cada grandeza
        ativos   = {sid for sid, var in self._sensores_vars.items() if var.get()}
        segundos = PERIODOS.get(self._periodo_var.get(), 30)
        temp, umid = {}, {}
        for sid in ativos:
            pts_t = self._buffer.get_filtrado(sid, "temperatura", segundos)
            pts_u = self._buffer.get_filtrado(sid, "umidade",     segundos)
            if pts_t:
                temp[sid] = self._agregar(pts_t)
            if pts_u:
                umid[sid] = self._agregar(pts_u)
        return temp, umid

    def _plotar_eixo(self, ax, dados: dict, tipo_key: str):
        # Plota as linhas de todos os sensores ativos em um eixo matplotlib
        cfg     = LIMITES[tipo_key]
        lim_max = cfg["max"]
        lim_min = cfg["min"]
        unidade = cfg["unidade"]
        titulo  = "Temperatura (°C)" if tipo_key == "temperatura" else "Umidade (%)"

        ax.clear()
        _estilo_ax(ax, ylabel=titulo)

        if not dados:
            ax.text(0.5, 0.5, f"sem dados · {titulo}",
                    transform=ax.transAxes, ha="center", va="center",
                    color=TX_MUTED, fontsize=9)
            return

        janela_s = PERIODOS.get(self._periodo_var.get(), 30)
        agora    = datetime.now()
        # Eixo X fixado na janela atual — mantém a escala estável enquanto os dados chegam
        ax.set_xlim(agora - timedelta(seconds=janela_s),
                    agora + timedelta(seconds=janela_s * 0.04))

        # Faixas coloridas e linhas tracejadas nos limites de alarme
        ax.axhspan(lim_max, lim_max + 5, color=COR_DANGER, alpha=0.06, zorder=0)
        ax.axhspan(lim_min - 5, lim_min, color=COR_COLD,   alpha=0.06, zorder=0)
        ax.axhline(lim_max, color=COR_DANGER, linewidth=0.7, linestyle="--", alpha=0.5, zorder=1)
        ax.axhline(lim_min, color=COR_COLD,   linewidth=0.7, linestyle="--", alpha=0.5, zorder=1)
        ax.annotate(f"max {lim_max}{unidade}",
                    xy=(0.99, lim_max), xycoords=("axes fraction", "data"),
                    xytext=(-4, 3), textcoords="offset points",
                    color=COR_DANGER, fontsize=6.5, ha="right", alpha=0.75)
        ax.annotate(f"min {lim_min}{unidade}",
                    xy=(0.99, lim_min), xycoords=("axes fraction", "data"),
                    xytext=(-4, 3), textcoords="offset points",
                    color=COR_COLD, fontsize=6.5, ha="right", alpha=0.75)

        all_vals = []
        for i, (sid, pontos) in enumerate(dados.items()):
            if not pontos:
                continue
            dts     = [p[0] for p in pontos]
            valores = [p[1] for p in pontos]
            all_vals.extend(valores)
            cor      = CORES_GRAF[i % len(CORES_GRAF)]
            nome_cur = sid.replace("sensor_", "").replace("_", " ")

            ax.plot(dts, valores, color=cor, linewidth=1.8,
                    marker="o", markersize=3,
                    label=nome_cur, zorder=3, alpha=0.92)
            ax.fill_between(dts, valores, alpha=0.07, color=cor, zorder=1)

            # Ponto vermelho destacado sobre leituras fora do limite
            for dt, val in zip(dts, valores):
                if val > lim_max or val < lim_min:
                    ax.plot(dt, val, "o", color=COR_DANGER,
                            markersize=5, zorder=5, markeredgewidth=0, alpha=0.8)

            # Anotação do valor mais recente ao lado direito da linha
            if pontos:
                offset_y = (i % 4) * 8 - 12  # escalonamento para não sobrepor rótulos
                ax.annotate(f"{valores[-1]:.1f}{unidade}",
                            xy=(dts[-1], valores[-1]),
                            xytext=(5, offset_y), textcoords="offset points",
                            color=cor, fontsize=7, va="center",
                            fontweight="bold", alpha=0.95, zorder=6)

        # Ajusta escala Y com margem para não cortar linhas nos extremos
        if all_vals:
            ax.set_ylim(min(min(all_vals), lim_min) - 2,
                        max(max(all_vals), lim_max) + 4)

        _formatar_eixo_x(ax, janela_s)

        ax.legend(facecolor=BG_PANEL, labelcolor=TX_SECONDARY, fontsize=7, loc="upper left",
                  framealpha=0.85, edgecolor=BORDER, ncol=min(len(dados), 3),
                  handlelength=1.2, handletextpad=0.5, borderpad=0.5, columnspacing=0.8)

    def _redesenhar(self):
        # Filtra e plota os dois eixos; chamado após mudança de período ou de seleção de sensor
        temp, umid = self._filtrar()
        self._plotar_eixo(self.ax_temp, temp, "temperatura")
        self._plotar_eixo(self.ax_umid, umid, "umidade")
        self.fig.tight_layout(pad=1.2)
        self.canvas.draw_idle()  # draw_idle é seguro chamar fora do loop principal

    # =========================================================================
    # LOOP PRINCIPAL DE ATUALIZAÇÃO
    # =========================================================================

    def _disparar_worker(self):
        # Garante que só uma thread de I/O roda por vez; reagenda a si mesmo a cada POLL_MS
        if not self._worker_rodando:
            self._worker_rodando = True
            threading.Thread(target=self._tarefa_io, daemon=True).start()
        self.after(self.POLL_MS, self._disparar_worker)

    def _tarefa_io(self):
        # Roda em thread separada: busca dados do servidor e coloca na fila da UI
        try:
            self._contador_poll += 1
            segundos  = PERIODOS.get(self._periodo_var.get(), 30)
            estado    = get_estado()
            historico = get_historico(segundos)

            # Atuadores são buscados a cada 4 ciclos (~2s) para reduzir requisições
            if self._contador_poll % 4 == 0:
                novos = get_atuadores()
                if novos:
                    self._cache_atuadores = novos

            self._buffer.ingest(historico)
            self._ui_queue.put({
                "tipo":      "dados",
                "estado":    estado,
                "atuadores": self._cache_atuadores,
                "n_reg":     len(historico),
                "tem_dado":  len(historico) > 0,
            })
        finally:
            self._worker_rodando = False  # libera o flag para o próximo ciclo

    def _processar_fila(self):
        # Consome todos os itens disponíveis na fila e atualiza a UI (roda na thread principal)
        while not self._ui_queue.empty():
            try:
                item = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            # Mensagens de acionamento manual exibem caixa de diálogo
            if item.get("tipo") == "msg_ativar":
                if item["ok"]:
                    messagebox.showinfo("Atuador", item["msg"])
                else:
                    messagebox.showerror("Erro", f"Falha ao contatar servidor:\n{item['msg']}")
                continue

            self._registrar_sensores(item["estado"])
            self._atualizar_status(item["estado"])

            # Só redesenha se passou tempo suficiente desde o último draw (evita sobrecarga)
            agora = time.time()
            if item["tem_dado"] and (agora - self._ultimo_draw >= self.DRAW_INTERVAL):
                self._redesenhar()
                self._ultimo_draw = agora

            self._atualizar_atuadores(item["atuadores"])

            self.status_bar.config(text=(
                f"  atualizado {datetime.now().strftime('%H:%M:%S')} · "
                f"período {self._periodo_var.get()} · "
                f"{item['n_reg']} registros · "
                f"{'online' if item['estado'] else 'sem conexão'}"
            ))

        # Reagenda a si mesmo a cada 50ms para manter a UI responsiva
        self.after(50, self._processar_fila)

    # =========================================================================
    # TROCA DE ABA
    # =========================================================================

    def _on_tab_change(self, event):
        # Atualiza o conteúdo da aba ao selecioná-la (dados podem ter mudado)
        tab = self.notebook.index(self.notebook.select())
        if tab == 1:
            self.after(0, self._atualizar_historico)
        elif tab == 2:
            self.after(0, self._atualizar_aba_atuadores)


if __name__ == "__main__":
    App().mainloop()