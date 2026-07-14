"""
calendar_service.py
--------------------
Módulo responsável pela integração real com a Google Calendar API.

Dependências (instale com):
    pip install google-auth google-auth-oauthlib google-api-python-client

Fluxo de autenticação (OAuth2 "Installed App"):
    1. Se já existir um `token.json` válido na raiz do projeto, ele é reutilizado
       (com refresh automático se estiver expirado, sem precisar logar de novo).
    2. Caso contrário, procura o arquivo `credentials.json` (baixado pelo usuário
       no Google Cloud Console) na raiz do projeto.
    3. Abre o navegador do usuário para o login/consentimento OAuth2
       (`InstalledAppFlow.run_local_server`).
    4. Ao concluir, salva o token gerado em `token.json` para logins
       automáticos nas próximas execuções.

Responsabilidades:
    - Gerenciar a obtenção/renovação de credenciais OAuth2 (`obter_credenciais_google`).
    - Criar eventos ("blocos de estudo") na agenda do usuário (`criar_bloco_estudo_agenda`).
    - Sinalizar erros de forma clara e amigável para a camada de UI (main.py).
"""

import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO
# ---------------------------------------------------------------------------

# Escopo estritamente necessário: apenas criar/gerenciar EVENTOS na agenda
# (não concede acesso para listar/alterar as configurações da agenda em si).
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

# Fuso horário padrão usado nos eventos criados (ajuste se necessário).
FUSO_HORARIO_PADRAO = "America/Fortaleza"

# `calendar_service.py` mora em src/services/. A raiz do projeto (onde o
# usuário deve colocar o `credentials.json` baixado do Google Cloud Console,
# e onde o `token.json` será salvo) é dois níveis acima.
# Se você reorganizar as pastas novamente, ajuste apenas estas duas linhas.
_DIR_SERVICE = os.path.dirname(os.path.abspath(__file__))
_DIR_RAIZ_PROJETO = os.path.dirname(os.path.dirname(_DIR_SERVICE))

CAMINHO_CREDENTIALS = os.path.join(_DIR_RAIZ_PROJETO, "credentials.json")
CAMINHO_TOKEN = os.path.join(_DIR_RAIZ_PROJETO, "token.json")


class CredentialsArquivoNaoEncontradoError(Exception):
    """Lançada quando `credentials.json` não é encontrado na raiz do projeto."""
    pass


class ErroAutenticacaoGoogleError(Exception):
    """Lançada quando o fluxo de login OAuth2 falha ou é cancelado pelo usuário."""
    pass


class ErroAgendaGoogleError(Exception):
    """Lançada quando a chamada à Google Calendar API falha (ex: Calendar ID inválido)."""
    pass


def obter_credenciais_google() -> Credentials:
    """
    Retorna credenciais OAuth2 válidas para acessar a Google Calendar API.

    - Reaproveita `token.json` se existir e ainda for válido (renovando
      automaticamente via refresh_token quando necessário).
    - Caso contrário, exige `credentials.json` na raiz do projeto e abre o
      navegador para o usuário autorizar o acesso (rodar isso em uma THREAD
      separada na UI, pois é uma chamada bloqueante que espera o login).

    Lança:
        CredentialsArquivoNaoEncontradoError: se não há token válido E
            `credentials.json` também não foi encontrado.
        ErroAutenticacaoGoogleError: se o fluxo de login falhar (ex: usuário
            cancelou, timeout, erro de rede durante o OAuth2).
    """
    credenciais = None

    if os.path.exists(CAMINHO_TOKEN):
        try:
            credenciais = Credentials.from_authorized_user_file(CAMINHO_TOKEN, SCOPES)
        except (ValueError, OSError):
            # token.json corrompido/ilegível — ignora e refaz o login do zero.
            credenciais = None

    if not credenciais or not credenciais.valid:
        if credenciais and credenciais.expired and credenciais.refresh_token:
            try:
                credenciais.refresh(Request())
            except Exception as e:
                raise ErroAutenticacaoGoogleError(
                    f"Falha ao renovar o login com o Google: {e}"
                ) from e
        else:
            if not os.path.exists(CAMINHO_CREDENTIALS):
                raise CredentialsArquivoNaoEncontradoError(
                    "Arquivo credentials.json não encontrado na raiz do projeto."
                )
            try:
                fluxo = InstalledAppFlow.from_client_secrets_file(CAMINHO_CREDENTIALS, SCOPES)
                # Abre o navegador padrão do usuário e aguarda o login/consentimento.
                credenciais = fluxo.run_local_server(port=0)
            except Exception as e:
                raise ErroAutenticacaoGoogleError(
                    f"Falha ao autenticar com o Google: {e}"
                ) from e

        # Salva/atualiza o token para reaproveitar em execuções futuras.
        with open(CAMINHO_TOKEN, "w", encoding="utf-8") as arquivo_token:
            arquivo_token.write(credenciais.to_json())

    return credenciais


def criar_bloco_estudo_agenda(
    calendar_id: str,
    titulo: str,
    data_inicio_iso: str,
    data_fim_iso: str,
    descricao: str = "",
) -> str:
    """
    Cria um evento ("bloco de estudo") na Google Agenda especificada.

    Parâmetros:
        calendar_id: o Calendar ID salvo pelo usuário nas Configurações
            (ex: o próprio e-mail do Google, para a agenda principal).
        titulo: título do evento (ex: "Estudo: Direito Administrativo").
        data_inicio_iso / data_fim_iso: strings ISO 8601 SEM offset de fuso
            (ex: "2026-07-10T14:00:00") — o fuso é aplicado via
            FUSO_HORARIO_PADRAO no corpo do evento.
        descricao: texto livre opcional para o corpo do evento.

    Retorna:
        O link (htmlLink) do evento criado na Google Agenda.

    Lança:
        CredentialsArquivoNaoEncontradoError / ErroAutenticacaoGoogleError:
            propagadas de `obter_credenciais_google()`.
        ErroAgendaGoogleError: se a API do Google Calendar rejeitar a
            criação do evento (ex: Calendar ID inexistente/sem permissão).
    """
    credenciais = obter_credenciais_google()

    corpo_evento = {
        "summary": titulo,
        "description": descricao,
        "start": {"dateTime": data_inicio_iso, "timeZone": FUSO_HORARIO_PADRAO},
        "end": {"dateTime": data_fim_iso, "timeZone": FUSO_HORARIO_PADRAO},
    }

    try:
        servico = build("calendar", "v3", credentials=credenciais)
        evento_criado = servico.events().insert(
            calendarId=calendar_id, body=corpo_evento
        ).execute()
    except HttpError as e:
        raise ErroAgendaGoogleError(
            f"O Google Calendar rejeitou a criação do evento. Verifique se o "
            f"Calendar ID '{calendar_id}' está correto e se você concedeu acesso "
            f"a ele durante o login. Detalhe: {e}"
        ) from e
    except Exception as e:
        raise ErroAgendaGoogleError(f"Erro inesperado ao criar o evento: {e}") from e

    link = evento_criado.get("htmlLink")
    if not link:
        raise ErroAgendaGoogleError("O evento foi criado, mas o Google não retornou um link.")

    return link


# Permite testar o módulo isoladamente: `python calendar_service.py`
if __name__ == "__main__":
    print(f"Raiz do projeto detectada: {_DIR_RAIZ_PROJETO}")
    print(f"Procurando credentials.json em: {CAMINHO_CREDENTIALS}")
    try:
        obter_credenciais_google()
        print("Autenticação OK — token.json salvo/atualizado.")
    except (CredentialsArquivoNaoEncontradoError, ErroAutenticacaoGoogleError) as e:
        print(f"[ERRO] {e}")
