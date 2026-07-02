"""
Hurst / Dimensión fractal por DFA en ventanas móviles
======================================================
DFA = Detrended Fluctuation Analysis. Estimador robusto del exponente
de Hurst (H), mucho mejor que R/S clásico en series cortas y ruidosas.

Relación clave:   D_fractal = 2 - H
  H > 0.5  -> persistente (tendencia)   -> D < 1.5  -> curva mas suave
  H = 0.5  -> paseo aleatorio puro       -> D = 1.5
  H < 0.5  -> anti-persistente (reversion)-> D > 1.5  -> curva mas rugosa

Uso con TUS datos:
  - Exporta un CSV con una columna de cierre (Close) desde thinkorswim
    o corre esto en tu maquina con yfinance.
  - Cambia USE_REAL_CSV = True y pon la ruta + nombre de columna.
"""

import numpy as np

# ----------------------------------------------------------------------
# 1. DFA: el estimador
# ----------------------------------------------------------------------
def dfa(x, scales=None):
    """
    Detrended Fluctuation Analysis.
    x: serie 1D (precios o log-precios).
    Devuelve el exponente alpha (~ Hurst para series tipo fGn integradas).
    """
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    N = len(x)
    if N < 50:
        return np.nan
    # perfil: serie integrada centrada
    y = np.cumsum(x - np.mean(x))
    if scales is None:
        # escalas log-espaciadas entre 4 y N/4
        scales = np.unique(np.floor(
            np.logspace(np.log10(4), np.log10(N // 4), 18)).astype(int))
        scales = scales[scales >= 4]
    F = []
    for s in scales:
        n_seg = N // s
        if n_seg < 1:
            continue
        rms = []
        # ventanas desde el inicio y desde el final (mas datos)
        for start in (0, N - n_seg * s):
            for i in range(n_seg):
                seg = y[start + i*s : start + (i+1)*s]
                t = np.arange(s)
                coef = np.polyfit(t, seg, 1)          # tendencia lineal local
                fit = np.polyval(coef, t)
                rms.append(np.mean((seg - fit) ** 2)) # varianza residual
        F.append(np.sqrt(np.mean(rms)))
    scales = scales[:len(F)]
    F = np.array(F)
    good = F > 0
    # pendiente en log-log = exponente
    alpha = np.polyfit(np.log(scales[good]), np.log(F[good]), 1)[0]
    return alpha

def rolling_hurst(prices, window=120, step=5):
    """H estimado sobre log-retornos en ventana movil."""
    logret = np.diff(np.log(prices))
    idx, H = [], []
    for end in range(window, len(logret) + 1, step):
        seg = logret[end - window:end]
        h = dfa(seg)
        H.append(h)
        idx.append(end)         # posicion en la serie de retornos
    return np.array(idx), np.array(H)

# ----------------------------------------------------------------------
# Demo / validación visual contra sintéticos.
# Solo corre al ejecutar el archivo directamente (`python hurst_dfa.py`).
# Al importarlo como módulo (p.ej. el motor de Hurst en backend/) NO se
# ejecuta nada de esto: dfa() y rolling_hurst() quedan disponibles puras.
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.gridspec import GridSpec

    np.random.seed(7)

    # ------------------------------------------------------------------
    # 2. Datos
    # ------------------------------------------------------------------
    USE_REAL_CSV = False
    CSV_PATH = "amd.csv"
    CLOSE_COL = "Close"

    def synthetic_three_regimes(n_each=380, s0=100.0):
        """Genera precio con 3 regimenes pegados: tendencia, aleatorio, reversion."""
        def fbm_like(n, H, sigma=0.012):
            # aproximacion simple: AR(1) sobre retornos para inducir memoria
            # phi>0 -> persistente; phi<0 -> anti-persistente
            phi = 2*(H - 0.5)            # H=0.7 -> phi=0.4 ; H=0.3 -> phi=-0.4
            e = np.random.randn(n) * sigma
            r = np.zeros(n)
            for t in range(1, n):
                r[t] = phi * r[t-1] + e[t]
            return r
        r1 = fbm_like(n_each, H=0.72)    # tendencia
        r2 = fbm_like(n_each, H=0.50)    # aleatorio
        r3 = fbm_like(n_each, H=0.30)    # reversion
        r = np.concatenate([r1, r2, r3])
        price = s0 * np.exp(np.cumsum(r))
        bounds = [n_each, 2*n_each]
        return price, bounds

    if USE_REAL_CSV:
        df = pd.read_csv(CSV_PATH)
        price = df[CLOSE_COL].dropna().values
        bounds = None
        title_src = f"datos reales: {CSV_PATH}"
    else:
        price, bounds = synthetic_three_regimes()
        title_src = "datos sinteticos (3 regimenes conocidos)"

    # ------------------------------------------------------------------
    # 3. Calcular
    # ------------------------------------------------------------------
    H_global = dfa(np.diff(np.log(price)))
    idx, H = rolling_hurst(price, window=120, step=4)
    D = 2 - H

    print(f"Fuente: {title_src}")
    print(f"H global (toda la serie): {H_global:.3f}   ->  D = {2-H_global:.3f}")
    print(f"H movil: rango [{np.nanmin(H):.2f}, {np.nanmax(H):.2f}]")

    # ------------------------------------------------------------------
    # 4. Graficar
    # ------------------------------------------------------------------
    plt.rcParams.update({
        "figure.facecolor": "#0a0e16", "axes.facecolor": "#0f1622",
        "axes.edgecolor": "#2a3a55", "text.color": "#e8ecf3",
        "axes.labelcolor": "#b8c2d6", "xtick.color": "#7d8aa3",
        "ytick.color": "#7d8aa3", "font.family": "monospace",
        "axes.grid": True, "grid.color": "#1b2436", "grid.linewidth": 0.6,
    })
    fig = plt.figure(figsize=(13, 8.5))
    gs = GridSpec(3, 1, height_ratios=[2, 1.5, 1.5], hspace=0.32)

    # precio
    ax0 = fig.add_subplot(gs[0])
    ax0.plot(price, color="#ffb347", lw=1.1)
    ax0.set_title(f"Precio  —  {title_src}", loc="left", fontsize=12, color="#e8ecf3")
    ax0.set_ylabel("precio")
    if bounds:
        for b in bounds:
            ax0.axvline(b, color="#4fd6c8", ls="--", lw=0.8, alpha=0.6)
        ax0.text(190, ax0.get_ylim()[1]*0.97, "TENDENCIA\nH≈0.72", color="#4fd6c8", fontsize=8, va="top", ha="center")
        ax0.text(570, ax0.get_ylim()[1]*0.97, "ALEATORIO\nH≈0.50", color="#7d8aa3", fontsize=8, va="top", ha="center")
        ax0.text(950, ax0.get_ylim()[1]*0.97, "REVERSIÓN\nH≈0.30", color="#ff7b72", fontsize=8, va="top", ha="center")

    # Hurst movil
    ax1 = fig.add_subplot(gs[1], sharex=ax0)
    ax1.plot(idx, H, color="#4fd6c8", lw=1.6)
    ax1.axhline(0.5, color="#7d8aa3", ls="--", lw=0.9)
    ax1.fill_between(idx, 0.5, H, where=(H>=0.5), color="#4fd6c8", alpha=0.18)
    ax1.fill_between(idx, 0.5, H, where=(H<0.5), color="#ff7b72", alpha=0.18)
    ax1.set_ylabel("H (Hurst)")
    ax1.set_ylim(0.1, 0.9)
    ax1.text(idx[2], 0.83, "↑ tendencia (continuación)", color="#4fd6c8", fontsize=8)
    ax1.text(idx[2], 0.16, "↓ reversión (mean-revert)", color="#ff7b72", fontsize=8)

    # dimension fractal
    ax2 = fig.add_subplot(gs[2], sharex=ax0)
    ax2.plot(idx, D, color="#ffb347", lw=1.6)
    ax2.axhline(1.5, color="#7d8aa3", ls="--", lw=0.9)
    ax2.set_ylabel("D = 2 − H\n(dim. fractal)")
    ax2.set_xlabel("barra (tiempo)")
    ax2.set_ylim(1.1, 1.9)
    ax2.text(idx[2], 1.83, "más rugosa →", color="#ffb347", fontsize=8)

    fig.suptitle("Régimen de mercado vía dimensión fractal (DFA)",
                 x=0.125, ha="left", fontsize=15, color="#e8ecf3", style="italic")
    plt.savefig("/home/claude/hurst_analysis.png", dpi=130, bbox_inches="tight",
                facecolor="#0a0e16")
    print("\nGuardado: hurst_analysis.png")
