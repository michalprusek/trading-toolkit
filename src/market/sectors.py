"""Centralized sector mapping, betas, and ETF definitions.

Single source of truth for symbol→sector mapping used by:
- risk-assessment agent (scenario analysis, tax-loss harvesting)
- sector-rotation agent (portfolio sector exposure)
Commands still use inline copies of SEMICONDUCTOR_SYMBOLS and SECTOR_ETFS
for now — to be migrated in a future PR.
"""

# 11 SPDR sector ETFs
SECTOR_ETFS = {
    'XLK': 'Technology',
    'XLF': 'Financials',
    'XLV': 'Healthcare',
    'XLE': 'Energy',
    'XLI': 'Industrials',
    'XLC': 'Communication',
    'XLY': 'ConsDiscr',
    'XLP': 'ConsStaples',
    'XLB': 'Materials',
    'XLU': 'Utilities',
    'XLRE': 'RealEstate',
}

# Sector proxy betas (well-established approximations vs SPY)
SECTOR_BETAS = {
    'XLK': 1.35, 'XLC': 1.20, 'XLY': 1.15, 'XLF': 1.10, 'XLE': 0.95,
    'XLI': 1.05, 'XLV': 0.75, 'XLP': 0.55, 'XLU': 0.50, 'XLB': 1.00,
    'XLRE': 0.85,
}

# Crypto symbols (beta ~2.5 vs SPY)
CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'SOL', 'ADA', 'XRP', 'DOGE', 'DOT', 'AVAX', 'LINK',
    'UNI', 'NEAR',
}

# Semiconductor sub-sector (for concentration checks)
SEMICONDUCTOR_SYMBOLS = {
    'NVDA', 'AMD', 'ASML', 'AMAT', 'MU', 'TSM', 'QCOM', 'MRVL', 'ARM',
    'SMCI', 'INTC', 'KLAC', 'LRCX', 'ON', 'TXN',
}

# Symbol → sector ETF mapping
SYMBOL_SECTOR_MAP = {
    # Technology (XLK)
    'AAPL': 'XLK', 'MSFT': 'XLK', 'NVDA': 'XLK', 'AMD': 'XLK',
    'AVGO': 'XLK', 'ORCL': 'XLK', 'CRM': 'XLK', 'ADBE': 'XLK',
    'INTC': 'XLK', 'CSCO': 'XLK', 'NOW': 'XLK', 'PLTR': 'XLK',
    'PANW': 'XLK', 'CRWD': 'XLK', 'DDOG': 'XLK', 'NET': 'XLK',
    'ZS': 'XLK', 'TEAM': 'XLK', 'MRVL': 'XLK', 'MU': 'XLK',
    'ANET': 'XLK', 'ASML': 'XLK', 'TSM': 'XLK', 'KLAC': 'XLK',
    'LRCX': 'XLK', 'QCOM': 'XLK', 'TXN': 'XLK', 'ON': 'XLK',
    'SMCI': 'XLK', 'ARM': 'XLK', 'DELL': 'XLK', 'WDAY': 'XLK', 'AMAT': 'XLK',
    'SNOW': 'XLK', 'XYZ': 'XLK',
    # Communication (XLC)
    'GOOGL': 'XLC', 'META': 'XLC', 'NFLX': 'XLC', 'DIS': 'XLC',
    'CMCSA': 'XLC', 'T': 'XLC', 'VZ': 'XLC',
    # Consumer Discretionary (XLY)
    'AMZN': 'XLY', 'TSLA': 'XLY', 'UBER': 'XLY', 'SHOP': 'XLY',
    'HD': 'XLY', 'NKE': 'XLY', 'SBUX': 'XLY', 'MCD': 'XLY',
    'TJX': 'XLY', 'BKNG': 'XLY', 'ABNB': 'XLY', 'CMG': 'XLY',
    # Financials (XLF)
    'JPM': 'XLF', 'BAC': 'XLF', 'GS': 'XLF', 'MS': 'XLF',
    'V': 'XLF', 'MA': 'XLF', 'BLK': 'XLF', 'AXP': 'XLF',
    'C': 'XLF', 'SCHW': 'XLF', 'PYPL': 'XLF', 'COIN': 'XLF',
    'SOFI': 'XLF', 'HOOD': 'XLF',
    # Healthcare (XLV)
    'UNH': 'XLV', 'JNJ': 'XLV', 'LLY': 'XLV', 'PFE': 'XLV',
    'ABBV': 'XLV', 'MRK': 'XLV', 'TMO': 'XLV', 'ABT': 'XLV',
    'AMGN': 'XLV', 'ISRG': 'XLV', 'GILD': 'XLV', 'REGN': 'XLV',
    'VRTX': 'XLV', 'MRNA': 'XLV',
    # Industrials & Defense (XLI)
    'LMT': 'XLI', 'RTX': 'XLI', 'NOC': 'XLI', 'GD': 'XLI',
    'LHX': 'XLI', 'HII': 'XLI', 'BA': 'XLI', 'LDOS': 'XLI',
    'CAT': 'XLI', 'DE': 'XLI', 'GE': 'XLI', 'HON': 'XLI',
    'UNP': 'XLI', 'MMM': 'XLI',
    # Energy (XLE)
    'XOM': 'XLE', 'CVX': 'XLE', 'COP': 'XLE', 'SLB': 'XLE',
    'EOG': 'XLE', 'MPC': 'XLE', 'PSX': 'XLE', 'OXY': 'XLE',
    # Consumer Staples (XLP)
    'PG': 'XLP', 'KO': 'XLP', 'PEP': 'XLP', 'COST': 'XLP',
    'WMT': 'XLP', 'CL': 'XLP',
    # Materials (XLB)
    'LIN': 'XLB', 'APD': 'XLB', 'FCX': 'XLB', 'NEM': 'XLB',
    # Real Estate (XLRE)
    'PLD': 'XLRE', 'AMT': 'XLRE', 'EQIX': 'XLRE', 'SPG': 'XLRE',
    # Utilities (XLU)
    'NEE': 'XLU', 'DUK': 'XLU', 'SO': 'XLU',
}


def get_sector(symbol: str) -> str:
    """Return sector ETF for a symbol. Returns 'CRYPTO' for crypto, 'OTHER' for unknown."""
    if symbol in CRYPTO_SYMBOLS:
        return 'CRYPTO'
    return SYMBOL_SECTOR_MAP.get(symbol, 'OTHER')


def get_beta(symbol: str) -> float:
    """Return estimated beta for a symbol vs SPY. Unknown symbols default to 1.0 (market beta)."""
    if symbol in CRYPTO_SYMBOLS:
        return 2.5
    sector = SYMBOL_SECTOR_MAP.get(symbol)
    if sector is None:
        return 1.0
    return SECTOR_BETAS.get(sector, 1.0)
