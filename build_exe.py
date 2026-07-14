"""
build_exe.py
------------
Script de build automatizado do GMBTech Dashboard para Windows.

Resolve os problemas clássicos do build local:
    1. PermissionError [WinError 5] — o Windows/OneDrive mantém um ponteiro
       aberto sobre a pasta 'dist/' de um build anterior.
    2. ModuleNotFoundError: No module named 'src' — resolvido via paths absolutos.
    3. ModuleNotFoundError: No module named 'sqlite3' — resolvido via hidden-import.
    4. URLError [SSL: CERTIFICATE_VERIFY_FAILED] — resolvido com injeção do certifi.
    5. No such file or directory 'icons.json' — resolvido com collect_data_files('flet').

Uso:
    python build_exe.py
"""

import os
import shutil
import sys
import time
import certifi

import PyInstaller.__main__
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

NOME_APP = "GMBTech_Dashboard"
RAIZ_PROJETO = os.path.abspath(os.path.dirname(__file__))
PASTA_BUILD = os.path.join(RAIZ_PROJETO, "build")
PASTA_DIST = os.path.join(RAIZ_PROJETO, "dist")
PASTA_SAIDA_FINAL = os.path.join(PASTA_DIST, NOME_APP)

MAX_TENTATIVAS_LIMPEZA = 5
SEGUNDOS_ENTRE_TENTATIVAS = 2


# ---------------------------------------------------------------------------
# PASSO 1 — Encerrar instâncias antigas travadas
# ---------------------------------------------------------------------------

def encerrar_processos_antigos() -> None:
    """Encerra silenciosamente qualquer instância antiga do executável no Windows."""
    print(">> Encerrando instâncias antigas do aplicativo (se houver)...")

    if os.name != "nt":
        print("   (pulado: este passo só é necessário no Windows)")
        return

    os.system(f"taskkill /f /im {NOME_APP}.exe >nul 2>&1")


# ---------------------------------------------------------------------------
# PASSO 2 — Limpar builds anteriores (com tentativas repetidas)
# ---------------------------------------------------------------------------

def _remover_pasta_com_tentativas(caminho_pasta: str) -> None:
    """Remove uma pasta com múltiplas tentativas (anti-lock do OneDrive)."""
    for tentativa in range(1, MAX_TENTATIVAS_LIMPEZA + 1):
        try:
            shutil.rmtree(caminho_pasta)
            print(f"   Removida: {caminho_pasta}")
            return
        except FileNotFoundError:
            return
        except (PermissionError, OSError) as erro:
            if tentativa == MAX_TENTATIVAS_LIMPEZA:
                print(
                    f"   [ERRO] Não foi possível remover '{caminho_pasta}' "
                    f"após {MAX_TENTATIVAS_LIMPEZA} tentativas: {erro}"
                )
                print(
                    "   Feche o executável antigo e qualquer Explorer/terminal "
                    "aberto dentro dessa pasta, depois rode este script novamente."
                )
                sys.exit(1)

            print(
                f"   Tentativa {tentativa}/{MAX_TENTATIVAS_LIMPEZA} falhou "
                f"({erro.__class__.__name__}: {erro}). "
                f"Tentando novamente em {SEGUNDOS_ENTRE_TENTATIVAS}s..."
            )
            time.sleep(SEGUNDOS_ENTRE_TENTATIVAS)


def limpar_pastas_antigas() -> None:
    """Remove as pastas 'build/' e 'dist/' de um build anterior, se existirem."""
    print(">> Limpando builds anteriores (build/ e dist/)...")

    for pasta in (PASTA_BUILD, PASTA_DIST):
        if os.path.exists(pasta):
            _remover_pasta_com_tentativas(pasta)
        else:
            print(f"   (nada a remover: {pasta} não existe)")


# ---------------------------------------------------------------------------
# PASSO 3 — Gerar o executável via API de código do PyInstaller
# ---------------------------------------------------------------------------

def gerar_executavel() -> None:
    """Chama o PyInstaller incluindo correções de caminhos, Google e ativos do Flet."""
    print(">> Gerando o executável com PyInstaller...")

    separador_add_data = ";" if os.name == "nt" else ":"

    # Coleta todos os arquivos adicionais e arquivos JSON internos do Flet (como o icons.json)
    print("   Coletando arquivos de dados e dicionários de ícones do Flet...")
    dados_flet = collect_data_files("flet")

    # Coleta de forma robusta e automática todos os submódulos das APIs utilizadas do Google
    print("   Varrendo submódulos do ecossistema Google (pode levar alguns segundos)...")
    hidden_google_genai = collect_submodules("google.genai")
    hidden_google_auth_oauthlib = collect_submodules("google_auth_oauthlib")
    hidden_google_api = collect_submodules("googleapiclient")
    hidden_google_auth = collect_submodules("google.auth")
    hidden_google_oauth2 = collect_submodules("google.oauth2")

    todos_hidden_imports_google = (
        hidden_google_genai
        + hidden_google_auth_oauthlib
        + hidden_google_api
        + hidden_google_auth
        + hidden_google_oauth2
    )
    print(f"   {len(todos_hidden_imports_google)} submódulos do Google serão incluídos explicitamente.")

    argumentos = [
        "--noconfirm",
        "--onedir",
        "--windowed",
        f"--name={NOME_APP}",
        "--hidden-import=sqlite3",
    ]

    # Injeta dinamicamente os dados internos coletados do Flet (icons.json, etc.)
    for orig, dest in dados_flet:
        argumentos.append(f"--add-data={orig}{separador_add_data}{dest}")

    # Injeta dinamicamente os submódulos encontrados na lista de hidden-imports
    for modulo in todos_hidden_imports_google:
        argumentos.append(f"--hidden-import={modulo}")

    # Certifi para SSL, caminhos absolutos e empacotamento da pasta de código src
    argumentos.extend([
        f"--add-data={certifi.where()}{separador_add_data}certifi",
        f"--paths={os.path.abspath('.')}",
        f"--add-data=src{separador_add_data}src",
        "main.py",
    ])

    PyInstaller.__main__.run(argumentos)


# ---------------------------------------------------------------------------
# PASSO 4 — Instruções finais para o usuário
# ---------------------------------------------------------------------------

def exibir_instrucoes_finais() -> None:
    print()
    print("=" * 72)
    print("BUILD CONCLUÍDO COM SUCESSO!")
    print("=" * 72)
    print(f"Executável gerado em: {PASTA_SAIDA_FINAL}")
    print()
    print("PRÓXIMO PASSO — Cole manualmente os arquivos de integração na RAIZ de:")
    print(f"   {PASTA_SAIDA_FINAL}")
    print("   - credentials.json")
    print("   - token.json")
    print()
    print("E o seu BANCO DE DADOS obrigatoriamente dentro da SUBPASTA:")
    print(f"   {PASTA_SAIDA_FINAL}\\src\\database")
    print("   - gmbtech_dashboard.db  (substitua o arquivo vazio por este)")
    print("=" * 72)


# ---------------------------------------------------------------------------
# PONTO DE ENTRADA
# ---------------------------------------------------------------------------

def main() -> None:
    encerrar_processos_antigos()
    limpar_pastas_antigas()
    gerar_executavel()
    exibir_instrucoes_finais()


if __name__ == "__main__":
    main()