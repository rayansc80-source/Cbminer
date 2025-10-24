#!/usr/bin/env python3
"""
bitcoinpuzzles_client.py
Script completo para integrar com a Pool BitcoinPuzzles (Desafio).
- Faz GET /api/block (ou /api/big_block)
- Chama mine_range() (placeholder) ou um minerador externo
- Envia 10 chaves via POST /api/block (ou /api/big_block)

Uso:
  python bitcoinpuzzles_client.py [--big] [--loop] [--miner-path /path/to/miner] [--delay 5]

Configuração:
  Crie ~/.bitcoinpuzzles.env com:
    POOL_TOKEN=seu_token_aqui
    BASE_URL=https://bitcoinpuzzles.com/api

Ou exporte variáveis de ambiente POOL_TOKEN e BASE_URL.
"""

import os
import sys
import argparse
import requests
import time
import subprocess
import shlex
import logging
from typing import List, Dict, Optional

# ----------------------------
# Config / Logging
# ----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bitcoinpuzzles_client")


# ----------------------------
# Helpers: load env file (~/.bitcoinpuzzles.env)
# ----------------------------
def load_env_file(path: str = "~/.bitcoinpuzzles.env") -> None:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


# ----------------------------
# Configuration values
# ----------------------------
load_env_file()  # try to load ~/.bitcoinpuzzles.env

POOL_TOKEN = os.getenv("POOL_TOKEN")
BASE_URL = os.getenv("BASE_URL", "https://bitcoinpuzzles.com/api")

if not POOL_TOKEN:
    logger.error("POOLTOKEN não encontrado. Configure POOL_TOKEN em ~/.bitcoinpuzzles.env ou exporte POOL_TOKEN.")
    # Do not exit here; we'll handle in runtime but warn user.
    # sys.exit(1)

HEADERS = {
    "pool-token": POOL_TOKEN if POOL_TOKEN else "",
    "Content-Type": "application/json",
}

REQUEST_TIMEOUT = 20  # segundos


# ----------------------------
# API functions
# ----------------------------
def get_block(big: bool = False) -> Dict:
    """
    GET /api/block or /api/big_block
    Retorna o JSON do bloco atribuído.
    """
    url = f"{BASE_URL}/big_block" if big else f"{BASE_URL}/block"
    logger.info("GET %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def submit_block(private_keys: List[str], big: bool = False) -> Dict:
    """
    POST /api/block or /api/big_block com {"privateKeys": [...]}
    """
    if not isinstance(private_keys, list) or len(private_keys) == 0:
        raise ValueError("private_keys precisa ser uma lista não-vazia.")
    url = f"{BASE_URL}/big_block" if big else f"{BASE_URL}/block"
    payload = {"privateKeys": private_keys}
    logger.info("POST %s (enviando %d chaves de prova)", url, len(private_keys))
    resp = requests.post(url, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


# ----------------------------
# Mining integration
# ----------------------------
def mine_range_placeholder(block_info: Dict) -> List[str]:
    """
    PLACEHOLDER seguro: não faz brute-force. Retorna 10 chaves de exemplo
    (válidas apenas como amostra). Substitua por sua lógica de mineração
    autorizada para produzir chaves reais do intervalo.
    """
    logger.info("Usando mine_range_placeholder (não faz varredura real).")
    # Exemplo: retorna 10 pseudo-chaves hex (0x...); substitua!
    base = "0x" + "0" * 62
    keys = []
    for i in range(1, 11):
        # Gera chaves diferentes só como placeholder
        k = base[:-len(hex(i)) + 2] + hex(i)[2:]  # crude but deterministic
        keys.append(k)
    return keys


def mine_range_with_external_binary(block_info: Dict, miner_path: str, max_keys: int = 10, timeout: int = 600) -> List[str]:
    """
    Chama um minerador externo (binário) passando o intervalo.
    O binário deve aceitar argumentos: --start <hex> --end <hex>
    e imprimir chaves privadas (uma por linha) no stdout. O script recolhe
    até `max_keys` chaves e fecha.
    - miner_path: caminho absoluto para o binário
    - timeout: tempo máximo em segundos para esperar o processo (None para aguardar indefinidamente)
    Retorna lista de chaves (até max_keys).
    """
    rng = block_info.get("range") or {}
    start = rng.get("start")
    end = rng.get("end")
    if not start or not end:
        raise ValueError("Bloco não contém 'range.start' e 'range.end'.")
    # montar comando
    cmd = f"{shlex.quote(miner_path)} --start {shlex.quote(str(start))} --end {shlex.quote(str(end))}"
    logger.info("Executando miner externo: %s", cmd)
    proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    keys = []
    try:
        start_ts = time.time()
        # Ler linhas do stdout até atingir max_keys ou timeout
        while True:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if line == "" and proc.poll() is not None:
                # processo terminou
                break
            if line:
                line = line.strip()
                if line:
                    keys.append(line)
                    logger.debug("Miner output key: %s", line)
                if len(keys) >= max_keys:
                    logger.info("Coletadas %d chaves do miner externo; finalizando processo.", max_keys)
                    proc.terminate()
                    break
            # timeout check
            if timeout and (time.time() - start_ts) > timeout:
                logger.warning("Timeout atingido esperando miner externo; terminando.")
                proc.terminate()
                break
        # tentar esperar finalização curta
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
    except Exception as e:
        logger.exception("Erro ao executar miner externo: %s", e)
        try:
            proc.kill()
        except Exception:
            pass
    # garantir retorno limitado
    return keys[:max_keys]


def mine_range(block_info: Dict, miner_path: Optional[str] = None) -> List[str]:
    """
    Função de alto nível que retorna até 10 chaves para enviar.
    - Se miner_path fornecido, tenta usar miner externo.
    - Caso contrário, usa o placeholder (de exemplo).
    Substitua por sua própria implementação de mineração autorizada.
    """
    if miner_path:
        try:
            keys = mine_range_with_external_binary(block_info, miner_path, max_keys=10)
            if keys:
                logger.info("Miner externo retornou %d chaves.", len(keys))
                return keys
            else:
                logger.warning("Miner externo não retornou chaves; usando placeholder.")
        except Exception as e:
            logger.exception("Falha ao usar miner externo: %s", e)
            logger.warning("Caindo para placeholder.")
    # fallback seguro
    return mine_range_placeholder(block_info)


# ----------------------------
# Main flow
# ----------------------------
def run_once(big: bool = False, miner_path: Optional[str] = None) -> None:
    if not POOL_TOKEN:
        logger.error("POOL_TOKEN não configurado. Abortando.")
        return

    try:
        block = get_block(big=big)
    except requests.HTTPError as e:
        logger.error("Erro HTTP ao obter bloco: %s", e)
        if getattr(e, "response", None) is not None:
            try:
                logger.error("Resposta: %s", e.response.text)
            except Exception:
                pass
        return
    except Exception as e:
        logger.exception("Erro ao obter bloco: %s", e)
        return

    logger.info("Bloco recebido: id=%s status=%s", block.get("id"), block.get("status"))
    rng = block.get("range")
    if not rng:
        logger.error("Bloco não contém 'range'. Saindo.")
        return
    logger.info("Range: start=%s end=%s", rng.get("start"), rng.get("end"))
    # show checkwork_addresses if available
    if block.get("checkwork_addresses"):
        logger.info("checkwork_addresses (exemplos): %s", block.get("checkwork_addresses")[:5])

    # Mine / integração
    keys_to_submit = mine_range(block, miner_path=miner_path)
    # garantia: enviar exatamente 10 chaves conforme API (se possível)
    if len(keys_to_submit) < 10:
        logger.warning("Somente %d chaves prontas para envio. Preenchendo com placeholders para totalizar 10.", len(keys_to_submit))
        # completar com placeholders (não são chaves válidas de fato)
        while len(keys_to_submit) < 10:
            keys_to_submit.append("0x" + os.urandom(16).hex().rjust(64, "0"))

    # cortar a 10 chaves
    keys_to_submit = keys_to_submit[:10]
    logger.info("Enviando %d chaves de prova...", len(keys_to_submit))
    try:
        resp = submit_block(keys_to_submit, big=big)
        logger.info("Resposta da pool: %s", resp)
    except requests.HTTPError as e:
        logger.error("Erro HTTP ao enviar bloco: %s", e)
        if getattr(e, "response", None) is not None:
            try:
                logger.error("Resposta: %s", e.response.text)
            except Exception:
                pass
    except Exception as e:
        logger.exception("Erro ao enviar chaves: %s", e)


def main():
    parser = argparse.ArgumentParser(description="Cliente Python para BitcoinPuzzles Pool")
    parser.add_argument("--big", action="store_true", help="Usar /api/big_block (intervalos maiores)")
    parser.add_argument("--loop", action="store_true", help="Rodar em loop contínuo")
    parser.add_argument("--delay", type=int, default=5, help="Delay (s) entre loops quando --loop (default 5s)")
    parser.add_argument("--miner-path", type=str, default=None, help="Caminho para minerador externo (opcional)")
    args = parser.parse_args()

    logger.info("Iniciando bitcoinpuzzles_client (big=%s loop=%s miner=%s)", args.big, args.loop, args.miner_path)

    try:
        if args.loop:
            while True:
                run_once(big=args.big, miner_path=args.miner_path)
                logger.info("Aguardando %s segundos antes do próximo ciclo...", args.delay)
                time.sleep(args.delay)
        else:
            run_once(big=args.big, miner_path=args.miner_path)
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário (Ctrl+C). Saindo.")
    except Exception:
        logger.exception("Erro inesperado no loop principal.")


if __name__ == "__main__":
    main()