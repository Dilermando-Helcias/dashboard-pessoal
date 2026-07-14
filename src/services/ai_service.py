"""
ai_service.py
--------------
Módulo responsável pela integração com o Google Gemini (Google AI Studio).

IMPORTANTE — escolha de SDK:
    O pacote `google-generativeai` (antigo) foi oficialmente descontinuado
    pelo Google em 30/11/2025 (End-of-Life). Este módulo usa o substituto
    oficial e atual, o SDK unificado `google-genai`:

        pip install google-genai

    Import: `from google import genai`
    A API do modelo (`gemini-2.5-flash`) e o comportamento de geração de
    texto seguem os mesmos princípios do SDK antigo, apenas com uma
    interface de cliente (`genai.Client`) diferente.

Responsabilidades:
    - Montar um prompt estruturado com o "raio-x" de desempenho do edital.
    - Chamar o modelo Gemini configurado com a API Key salva pelo usuário.
    - Ler editais em PDF (mesmo baseados em imagem/escaneados) usando a
      capacidade nativa de leitura de documentos do Gemini, extraindo a
      estrutura de matérias/tópicos sem precisar de OCR.
    - Tratar e sinalizar erros de forma clara para a camada de UI (main.py).
"""

import json
import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import database as db

# Chave usada na tabela `configuracoes` para armazenar a API Key.
CHAVE_API_GOOGLE_AI = "google_ai_studio_api_key"

# Modelo recomendado para análises de texto rápidas e de baixo custo.
# O mesmo modelo também é usado para leitura nativa de PDF (extração de edital).
MODELO_PADRAO = "gemini-2.5-flash"


class ApiKeyNaoConfiguradaError(Exception):
    """Lançada quando não existe nenhuma API Key salva na tabela `configuracoes`."""
    pass


class ApiKeyInvalidaError(Exception):
    """Lançada quando a API Key está presente, mas foi rejeitada pelo Google (401/403)."""
    pass


class ErroAnaliseIA(Exception):
    """Lançada para qualquer outro erro ocorrido durante a chamada ao Gemini."""
    pass


def _obter_api_key() -> str:
    """
    Recupera a API Key salva na tabela `configuracoes`.
    Lança ApiKeyNaoConfiguradaError caso não exista ou esteja vazia.
    """
    api_key = db.obter_configuracao(CHAVE_API_GOOGLE_AI)
    if not api_key or not api_key.strip():
        raise ApiKeyNaoConfiguradaError(
            "Nenhuma Google AI Studio API Key foi configurada. "
            "Acesse a aba Configurações para cadastrá-la."
        )
    return api_key.strip()


def _montar_prompt(nome_edital: str, estatisticas_por_materia: list, historico_simulados: dict) -> str:
    """
    Monta o prompt estruturado enviado ao Gemini, combinando:
        - O raio-x de progresso (tópicos vistos/não iniciados) por matéria.
        - Os dados BRUTOS de desempenho em questões/simulados (tabela `simulados`),
          para que o próprio Gemini calcule o percentual de acertos por matéria
          e identifique exatamente onde o candidato está errando mais.
    """
    total_geral = sum(m["total_topicos"] for m in estatisticas_por_materia)
    vistos_geral = sum(m["topicos_vistos"] for m in estatisticas_por_materia)
    percentual_geral = round((vistos_geral / total_geral) * 100, 1) if total_geral else 0.0

    linhas_materias = []
    for m in estatisticas_por_materia:
        linhas_materias.append(
            f"- {m['materia']}: {m['topicos_vistos']}/{m['total_topicos']} tópicos vistos "
            f"({m['percentual_concluido']}% concluído), "
            f"{m['topicos_nao_iniciados']} tópico(s) não iniciado(s)."
        )
    bloco_materias = "\n".join(linhas_materias) if linhas_materias else "Nenhuma matéria cadastrada."

    # --- Bloco de dados BRUTOS de simulados/questões -----------------------
    evolucao = historico_simulados.get("evolucao", [])
    if evolucao:
        linhas_evolucao = []
        for registro in evolucao:
            alvo = registro["topico"] or f"(geral da matéria {registro['materia']})"
            linhas_evolucao.append(
                f"- [{registro['data']}] {registro['materia']} / {alvo}: "
                f"{registro['acertos']}/{registro['total_questoes']} acertos "
                f"({registro['percentual']}%)"
            )
        bloco_evolucao = "\n".join(linhas_evolucao)
    else:
        bloco_evolucao = "Nenhuma sessão de questões/simulados registrada ainda."

    materias_criticas = historico_simulados.get("materias_criticas", [])
    if materias_criticas:
        linhas_criticas = [
            f"- {m['materia']}: {m['acertos']}/{m['total_questoes']} acertos "
            f"({m['percentual_acertos']}% de aproveitamento)"
            for m in materias_criticas
        ]
        bloco_criticas = "\n".join(linhas_criticas)
    else:
        bloco_criticas = "Sem dados de desempenho em questões ainda."

    prompt = f"""
Você é um mentor especialista em preparação para concursos públicos brasileiros.
Analise os dados abaixo do candidato e produza um plano de ataque cirúrgico.

EDITAL: {nome_edital}
PROGRESSO GERAL DE ESTUDO (tópicos revisados): {vistos_geral}/{total_geral} tópicos vistos ({percentual_geral}%)

DESEMPENHO POR MATÉRIA (tópicos vistos vs. não iniciados):
{bloco_materias}

DADOS BRUTOS DE SESSÕES DE QUESTÕES/SIMULADOS (ordem cronológica, mais antiga primeiro):
{bloco_evolucao}

TOTAIS DE ACERTOS POR MATÉRIA (soma de todas as sessões de questões, já ordenado do PIOR para o MELHOR aproveitamento):
{bloco_criticas}

Com base exclusivamente nesses dados, responda em Markdown, de forma direta e objetiva, contendo:

1. **Diagnóstico rápido** (1-2 frases sobre a situação geral do candidato, cruzando progresso de
   estudo com desempenho real em questões).
2. **Matérias prioritárias**: liste as 2-3 matérias que devem ser priorizadas agora, justificando
   com base no percentual de conclusão E no percentual de acertos em questões.
3. **Plano de Revisão de Erros**: calcule você mesmo o percentual de acertos por matéria a partir
   dos dados brutos acima e aponte EXATAMENTE onde o candidato está errando mais (matéria e, se
   houver, o tópico específico). Seja específico com os números que você calculou.
4. **Ritmo sugerido**: uma recomendação prática de ritmo de estudo semanal para equilibrar as
   matérias atrasadas/com baixo aproveitamento sem abandonar as demais.
5. **Insight motivacional curto**: uma frase curta e direta para manter o candidato engajado,
   sem ser genérica.

Seja objetivo. Não repita os dados brutos, apenas interprete-os e calcule os percentuais pedidos.
""".strip()

    return prompt


def analisar_progresso_edital(edital_id: int) -> str:
    """
    Gera uma análise de progresso do edital usando o Gemini.

    Fluxo:
        1. Busca a API Key salva (lança ApiKeyNaoConfiguradaError se ausente).
        2. Busca o edital, as estatísticas por matéria e o histórico de
           desempenho em simulados/questões no banco de dados.
        3. Monta o prompt estruturado com o raio-x do candidato + dados
           brutos de acertos/erros, pedindo um Plano de Revisão de Erros.
        4. Chama o modelo `gemini-2.5-flash` via SDK oficial `google-genai`.
        5. Retorna o texto da resposta (Markdown).

    Lança:
        ApiKeyNaoConfiguradaError: se nenhuma API Key foi salva.
        ApiKeyInvalidaError: se a API Key foi rejeitada pelo Google.
        ValueError: se o edital não existir ou não tiver matérias cadastradas.
        ErroAnaliseIA: para qualquer outro erro de comunicação com a API.
    """
    api_key = _obter_api_key()

    edital = db.obter_edital_por_id(edital_id)
    if edital is None:
        raise ValueError("Edital não encontrado.")

    estatisticas = db.obter_estatisticas_por_materia(edital_id)
    if not estatisticas:
        raise ValueError(
            "Este edital ainda não possui matérias/tópicos cadastrados para análise."
        )

    historico_simulados = db.obter_historico_desempenho(edital_id)

    prompt = _montar_prompt(edital["nome"], estatisticas, historico_simulados)

    try:
        client = genai.Client(api_key=api_key)
        resposta = client.models.generate_content(
            model=MODELO_PADRAO,
            contents=prompt,
        )
    except genai_errors.ClientError as e:
        # Erros 4xx da API (400/401/403/404) — normalmente API Key inválida,
        # sem permissão, ou modelo/projeto incorreto.
        mensagem = str(e)
        if any(codigo in mensagem for codigo in ("API_KEY_INVALID", "401", "403", "PERMISSION_DENIED")):
            raise ApiKeyInvalidaError(
                "A API Key configurada foi rejeitada pelo Google. "
                "Verifique se ela está correta na aba Configurações."
            ) from e
        raise ErroAnaliseIA(f"Erro ao chamar a API do Gemini: {mensagem}") from e
    except genai_errors.ServerError as e:
        raise ErroAnaliseIA(
            f"O serviço do Gemini está indisponível no momento. Tente novamente em instantes. ({e})"
        ) from e
    except Exception as e:
        raise ErroAnaliseIA(f"Erro inesperado ao comunicar com a IA: {e}") from e

    texto = getattr(resposta, "text", None)
    if not texto:
        raise ErroAnaliseIA("O Gemini retornou uma resposta vazia.")

    return texto.strip()


# ---------------------------------------------------------------------------
# IMPORTAÇÃO DE EDITAL VIA PDF (leitura nativa de documento pelo Gemini)
# ---------------------------------------------------------------------------
# Muitos editais reais (inclusive "verticalizados") são PDFs baseados em
# imagem/tabela SEM camada de texto extraível — OCR tradicional (pypdf,
# pdfplumber) não funciona neles. Em vez de adicionar uma dependência de OCR
# pesada, aproveitamos que o `gemini-2.5-flash` lê PDFs nativamente (inclusive
# baseados em imagem) e pedimos a ele para estruturar o conteúdo programático
# já no formato aceito por `database.importar_edital_dict`.

PROMPT_EXTRACAO_EDITAL_PDF = """
Você é um especialista em concursos públicos brasileiros. Analise o PDF anexado,
que é o conteúdo programático de um edital de concurso (pode estar no formato
"verticalizado", com tabelas de Assunto/Teoria/Exercícios/Revisão).

Extraia a ESTRUTURA do conteúdo programático e devolva ESTRITAMENTE um JSON
no formato:

{
  "concurso": "Nome do concurso/cargo (ex: Guarda Municipal de Baturité - GM Baturité)",
  "materias": {
    "Nome da Matéria 1": ["Tópico A", "Tópico B", "Tópico C"],
    "Nome da Matéria 2": ["Tópico X", "Tópico Y"]
  }
}

Regras:
- Use os nomes das matérias/áreas de conhecimento exatamente como aparecem no
  documento (ex: "Língua Portuguesa", "Noções de Administração Pública").
- Cada linha da coluna "Assunto" (ou equivalente) deve se tornar um tópico da
  matéria correspondente. Use seu julgamento para manter granularidade útil
  para estudo — nem um tópico gigante só, nem fragmentos sem sentido isolado.
- IGNORE colunas de controle (Teoria, Exercícios, Revisão, Total, Erros,
  Acertos, 1º/2º/3º) e qualquer tabela de pontuação/pesos da prova — extraia
  SOMENTE o conteúdo programático (matérias e seus tópicos).
- Se o nome exato do concurso/cargo não estiver explícito, use o título do
  documento ou o cargo mencionado como "concurso".
- Retorne APENAS o JSON, sem markdown, sem crases, sem texto antes ou depois.
""".strip()


def extrair_estrutura_edital_pdf(caminho_pdf: str) -> dict:
    """
    Lê um edital em PDF (mesmo baseado em imagem/escaneado) usando a
    capacidade nativa de leitura de documentos do Gemini, e devolve a
    estrutura já no formato aceito por `database.importar_edital_dict`:

        {"concurso": str, "materias": {materia: [topicos]}}

    Lança:
        FileNotFoundError: se o PDF não existir no caminho informado.
        ApiKeyNaoConfiguradaError / ApiKeyInvalidaError: propagadas.
        ErroAnaliseIA: se o Gemini falhar ao processar o PDF ou devolver
            algo que não seja um JSON válido no formato esperado.
    """
    if not os.path.exists(caminho_pdf):
        raise FileNotFoundError(f"Arquivo PDF não encontrado: {caminho_pdf}")

    api_key = _obter_api_key()

    with open(caminho_pdf, "rb") as arquivo_pdf:
        pdf_bytes = arquivo_pdf.read()

    try:
        client = genai.Client(api_key=api_key)
        resposta = client.models.generate_content(
            model=MODELO_PADRAO,
            contents=[
                types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
                PROMPT_EXTRACAO_EDITAL_PDF,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
    except genai_errors.ClientError as e:
        mensagem = str(e)
        if any(codigo in mensagem for codigo in ("API_KEY_INVALID", "401", "403", "PERMISSION_DENIED")):
            raise ApiKeyInvalidaError(
                "A API Key configurada foi rejeitada pelo Google. "
                "Verifique se ela está correta na aba Configurações."
            ) from e
        raise ErroAnaliseIA(f"Erro ao chamar a API do Gemini com o PDF: {mensagem}") from e
    except genai_errors.ServerError as e:
        raise ErroAnaliseIA(
            f"O serviço do Gemini está indisponível no momento. Tente novamente em instantes. ({e})"
        ) from e
    except Exception as e:
        raise ErroAnaliseIA(f"Erro inesperado ao enviar o PDF para a IA: {e}") from e

    texto = getattr(resposta, "text", None)
    if not texto:
        raise ErroAnaliseIA("O Gemini retornou uma resposta vazia ao processar o PDF.")

    texto_limpo = texto.strip()
    if texto_limpo.startswith("```"):
        # Defesa extra: remove eventuais crases de markdown, mesmo com
        # response_mime_type="application/json" configurado.
        texto_limpo = texto_limpo.strip("`")
        if texto_limpo.lower().startswith("json"):
            texto_limpo = texto_limpo[4:].strip()

    try:
        estrutura = json.loads(texto_limpo)
    except json.JSONDecodeError as e:
        raise ErroAnaliseIA(
            f"O Gemini não devolveu um JSON válido ao processar o PDF. Detalhe: {e}"
        ) from e

    if not isinstance(estrutura, dict) or "concurso" not in estrutura or "materias" not in estrutura:
        raise ErroAnaliseIA(
            "O Gemini devolveu uma estrutura inesperada ao processar o PDF "
            "(faltam as chaves 'concurso'/'materias')."
        )

    return estrutura


# Permite testar o módulo isoladamente (requer uma API Key já salva no banco).
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Uso: python ai_service.py <edital_id>")
        sys.exit(1)

    try:
        resultado = analisar_progresso_edital(int(sys.argv[1]))
        print(resultado)
    except (ApiKeyNaoConfiguradaError, ApiKeyInvalidaError, ValueError, ErroAnaliseIA) as e:
        print(f"[ERRO] {e}")