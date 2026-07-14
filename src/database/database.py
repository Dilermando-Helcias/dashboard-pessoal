"""
database.py
------------
Módulo responsável por toda a camada de persistência do GMBTech Dashboard.

Responsabilidades:
    - Criar/inicializar o banco de dados SQLite e suas tabelas.
    - CRUD de configurações (ex: API Key do Google AI Studio).
    - Importação dinâmica de editais a partir de arquivos JSON.
    - Consultas de leitura para popular a interface (editais, matérias, tópicos).
    - Atualização de status de estudo dos tópicos.

Este módulo não possui nenhuma dependência de UI (Flet), podendo ser testado
e reutilizado de forma isolada.
"""

import sqlite3
import json
import os
import itertools
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

# Nome/caminho do arquivo do banco de dados SQLite.
# Fica na mesma pasta do executável/script, garantindo portabilidade.
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gmbtech_dashboard.db")


@contextmanager
def conectar():
    """
    Context manager que abre uma conexão com o SQLite, ativa o suporte
    a chaves estrangeiras (FOREIGN KEY) e garante o commit/close correto,
    inclusive em caso de exceção (rollback automático).

    Uso:
        with conectar() as conn:
            cursor = conn.cursor()
            cursor.execute(...)
    """
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row  # Permite acessar colunas por nome (linha["nome"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def inicializar_banco() -> None:
    """
    Cria todas as tabelas do sistema caso ainda não existam.
    Deve ser chamada uma única vez, no início da aplicação (main.py).
    """
    with conectar() as conn:
        cursor = conn.cursor()

        # Tabela de configurações gerais (chave/valor) -> usada para API_KEY, preferências, etc.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS configuracoes (
                chave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)

        # Tabela de editais (concursos) importados.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS editais (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL UNIQUE,
                data_criacao TEXT,
                caminho_pdf TEXT
            )
        """)

        # Migração segura: bancos criados em versões anteriores não têm a
        # coluna `caminho_pdf`. Adiciona só se ainda não existir (evita
        # "duplicate column name" em execuções repetidas).
        colunas_editais = {linha["name"] for linha in cursor.execute("PRAGMA table_info(editais)")}
        if "caminho_pdf" not in colunas_editais:
            cursor.execute("ALTER TABLE editais ADD COLUMN caminho_pdf TEXT")
        if "data_prova" not in colunas_editais:
            cursor.execute("ALTER TABLE editais ADD COLUMN data_prova TEXT")
        if "capacidade_diaria_min" not in colunas_editais:
            cursor.execute(
                "ALTER TABLE editais ADD COLUMN capacidade_diaria_min INTEGER DEFAULT 120"
            )

        # Tabela de matérias, vinculadas a um edital.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS materias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edital_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                FOREIGN KEY(edital_id) REFERENCES editais(id) ON DELETE CASCADE
            )
        """)

        # Tabela de tópicos, vinculados a uma matéria.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS topicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                materia_id INTEGER NOT NULL,
                nome TEXT NOT NULL,
                status TEXT DEFAULT 'Não Iniciado',
                rendimento_simulados REAL DEFAULT 0.0,
                FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE
            )
        """)

        # Tabela de registros de desempenho em simulados/treinos de questões.
        # Cada linha representa UMA sessão de questões feitas pelo usuário
        # (ex: "fiz 20 questões de Crase, acertei 14").
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS simulados (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edital_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                total_questoes INTEGER NOT NULL,
                acertos INTEGER NOT NULL,
                materia_id INTEGER NOT NULL,
                topico_id INTEGER,
                FOREIGN KEY(edital_id) REFERENCES editais(id) ON DELETE CASCADE,
                FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE,
                FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE SET NULL
            )
        """)

        # --- Módulo Estudos: cronograma dinâmico e meta diária de questões --
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cronograma_estudos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edital_id INTEGER NOT NULL,
                materia_id INTEGER NOT NULL,
                topico_id INTEGER,
                data TEXT NOT NULL,
                tipo_atividade TEXT NOT NULL,
                tempo_estimado_min INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'Pendente',
                fonte_estudo TEXT,
                notas TEXT,
                FOREIGN KEY(edital_id) REFERENCES editais(id) ON DELETE CASCADE,
                FOREIGN KEY(materia_id) REFERENCES materias(id) ON DELETE CASCADE,
                FOREIGN KEY(topico_id) REFERENCES topicos(id) ON DELETE SET NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS meta_questoes_diaria (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edital_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                meta_questoes INTEGER NOT NULL,
                UNIQUE(edital_id, data),
                FOREIGN KEY(edital_id) REFERENCES editais(id) ON DELETE CASCADE
            )
        """)

        # --- Módulo Faculdade: disciplinas cursadas, faltas e notas ---------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS faculdade_materias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                professor TEXT,
                faltas INTEGER DEFAULT 0,
                m1 REAL DEFAULT 0.0,
                m2 REAL DEFAULT 0.0,
                media_final REAL DEFAULT 0.0
            )
        """)

        # --- Módulo Clientes & Freelas: projetos/freelas em andamento ------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes_projetos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_projeto TEXT NOT NULL,
                cliente TEXT,
                prazo TEXT,
                valor REAL DEFAULT 0.0,
                status TEXT DEFAULT 'Em Andamento',
                entregas TEXT
            )
        """)

        # --- Módulo Rotina & Hábitos: hábitos diários (checkbox por dia) ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rotina_habitos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_habito TEXT NOT NULL,
                segunda INTEGER DEFAULT 0,
                terca INTEGER DEFAULT 0,
                quarta INTEGER DEFAULT 0,
                quinta INTEGER DEFAULT 0,
                sexta INTEGER DEFAULT 0,
                sabado INTEGER DEFAULT 0,
                domingo INTEGER DEFAULT 0
            )
        """)

        colunas_habitos = {linha["name"] for linha in cursor.execute("PRAGMA table_info(rotina_habitos)")}
        if "horario" not in colunas_habitos:
            cursor.execute("ALTER TABLE rotina_habitos ADD COLUMN horario TEXT")

        # --- Módulo Rotina & Hábitos: tarefas avulsas e atividades extras ---
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tarefas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                descricao TEXT,
                data TEXT,
                horario TEXT,
                prioridade TEXT NOT NULL DEFAULT 'Média',
                status TEXT NOT NULL DEFAULT 'Pendente',
                origem TEXT NOT NULL DEFAULT 'Planejada'
            )
        """)

        # --- Módulo Financeiro: controle de boletos mensais ----------------
        # `data_vencimento` sempre no formato 'YYYY-MM-DD' (ISO), para que
        # filtros por mês ('YYYY-MM%') e ordenação por data funcionem por
        # simples comparação de string, sem precisar converter tipos.
        conn.execute('''
            CREATE TABLE IF NOT EXISTS boletos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                valor REAL NOT NULL,
                data_vencimento TEXT NOT NULL,
                codigo_barras TEXT,
                status TEXT NOT NULL DEFAULT 'Pendente'
            )
        ''')

        # ------------------------------------------------------------------
        # Fluxo de Caixa
        # ------------------------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                descricao TEXT NOT NULL,
                valor REAL NOT NULL,
                tipo TEXT NOT NULL,
                categoria TEXT NOT NULL,
                data TEXT NOT NULL
            )
        """)

        # ------------------------------------------------------------------
        # Metas de Investimento / Poupança
        # ------------------------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metas_investimento (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_meta TEXT NOT NULL,
                valor_alvo REAL NOT NULL,
                valor_atual REAL NOT NULL DEFAULT 0.0
            )
        """)

        # ------------------------------------------------------------------
        # Empréstimos (Financeiro)
        # ------------------------------------------------------------------

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes_emprestimo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                contato TEXT,
                observacoes TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS emprestimos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                valor_principal REAL NOT NULL,
                taxa_juros_mensal REAL NOT NULL,
                modalidade TEXT NOT NULL,
                valor_parcela_principal REAL,
                data_inicio TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ativo',
                FOREIGN KEY (cliente_id) REFERENCES clientes_emprestimo(id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parcelas_emprestimo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emprestimo_id INTEGER NOT NULL,
                numero INTEGER NOT NULL,
                valor_juros REAL NOT NULL,
                valor_principal REAL NOT NULL DEFAULT 0,
                data_vencimento TEXT NOT NULL,
                data_pagamento TEXT,
                status TEXT NOT NULL DEFAULT 'pendente',
                FOREIGN KEY (emprestimo_id) REFERENCES emprestimos(id)
            )
        """)

        # --- Módulo Veículos: cadastro, plano de manutenção, histórico e ----
        # --- abastecimentos --------------------------------------------------
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS veiculos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                apelido TEXT NOT NULL,
                tipo TEXT NOT NULL,
                marca TEXT,
                modelo TEXT,
                ano INTEGER,
                km_atual INTEGER NOT NULL DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS itens_manutencao_veiculo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veiculo_id INTEGER NOT NULL,
                nome_item TEXT NOT NULL,
                intervalo_km INTEGER,
                intervalo_dias INTEGER,
                km_ultima_troca INTEGER,
                data_ultima_troca TEXT,
                criticidade TEXT NOT NULL DEFAULT 'Média',
                FOREIGN KEY(veiculo_id) REFERENCES veiculos(id) ON DELETE CASCADE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manutencoes_realizadas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veiculo_id INTEGER NOT NULL,
                item_id INTEGER,
                descricao TEXT NOT NULL,
                data TEXT NOT NULL,
                km INTEGER,
                custo REAL,
                local TEXT,
                FOREIGN KEY(veiculo_id) REFERENCES veiculos(id) ON DELETE CASCADE,
                FOREIGN KEY(item_id) REFERENCES itens_manutencao_veiculo(id) ON DELETE SET NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS abastecimentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                veiculo_id INTEGER NOT NULL,
                data TEXT NOT NULL,
                km INTEGER NOT NULL,
                litros REAL NOT NULL,
                valor_total REAL NOT NULL,
                combustivel TEXT NOT NULL,
                FOREIGN KEY(veiculo_id) REFERENCES veiculos(id) ON DELETE CASCADE
            )
        """)

        cursor.close()

    print(f"[database] Banco de dados inicializado em: {DB_NAME}")


# ---------------------------------------------------------------------------
# CONFIGURAÇÕES (chave/valor)
# ---------------------------------------------------------------------------

def salvar_configuracao(chave: str, valor: str) -> None:
    """
    Salva (ou atualiza, caso já exista) um par chave/valor na tabela
    'configuracoes'. Usado principalmente para persistir a API Key.
    """
    with conectar() as conn:
        conn.execute("""
            INSERT INTO configuracoes (chave, valor)
            VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
        """, (chave, valor))


def obter_configuracao(chave: str, padrao: Optional[str] = None) -> Optional[str]:
    """
    Recupera o valor de uma configuração pela chave.
    Retorna `padrao` caso a chave não exista.
    """
    with conectar() as conn:
        cursor = conn.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,))
        linha = cursor.fetchone()
        return linha["valor"] if linha else padrao


# ---------------------------------------------------------------------------
# IMPORTAÇÃO DE EDITAIS (JSON)
# ---------------------------------------------------------------------------

def importar_edital_json(caminho_arquivo: str) -> Dict[str, Any]:
    """
    Lê um arquivo JSON no formato:
        {
            "concurso": "Nome do Concurso",
            "materias": {
                "Matéria 1": ["Tópico A", "Tópico B"],
                "Matéria 2": ["Tópico X"]
            }
        }
    E insere o edital, suas matérias e tópicos no banco de dados (via
    `importar_edital_dict`, que faz o trabalho de fato).

    Lança:
        FileNotFoundError: se o arquivo não existir.
        ValueError: se o JSON estiver malformado ou fora do formato esperado.
    """
    if not os.path.exists(caminho_arquivo):
        raise FileNotFoundError(f"Arquivo não encontrado: {caminho_arquivo}")

    with open(caminho_arquivo, "r", encoding="utf-8") as f:
        try:
            dados = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON inválido: {e}")

    return importar_edital_dict(dados)


def importar_edital_dict(dados: Dict[str, Any]) -> Dict[str, Any]:
    """
    Insere o edital, suas matérias e tópicos no banco de dados a partir de
    um dicionário Python já no formato:
        {
            "concurso": "Nome do Concurso",
            "materias": {
                "Matéria 1": ["Tópico A", "Tópico B"],
                "Matéria 2": ["Tópico X"]
            }
        }

    Esta é a função "core" de importação — usada tanto pelo fluxo de JSON
    (`importar_edital_json`, que só lê o arquivo e delega para cá) quanto
    pelo fluxo de importação via PDF com IA (`ai_service.extrair_estrutura_edital_pdf`
    gera exatamente este dicionário a partir do PDF lido pelo Gemini).

    Regras de duplicidade:
        - Se o edital (mesmo nome) já existir, ele é reaproveitado (não duplica o edital).
        - Se uma matéria com o mesmo nome já existir dentro do edital, ela é reaproveitada.
        - Se um tópico com o mesmo nome já existir dentro da matéria, ele é ignorado
          (não duplica o tópico, preservando o status/rendimento já registrados).

    Retorna um dicionário de resumo da importação:
        {
            "edital_id": int,
            "concurso": str,
            "materias_inseridas": int,
            "topicos_inseridos": int,
            "topicos_ignorados_duplicados": int
        }

    Lança:
        ValueError: se `dados` estiver fora do formato esperado.
    """
    concurso = dados.get("concurso")
    materias_json = dados.get("materias")

    if not concurso or not isinstance(materias_json, dict):
        raise ValueError(
            "Formato de dados inválido. Esperado: {'concurso': str, 'materias': {materia: [topicos]}}"
        )

    resumo = {
        "edital_id": None,
        "concurso": concurso,
        "materias_inseridas": 0,
        "topicos_inseridos": 0,
        "topicos_ignorados_duplicados": 0,
    }

    with conectar() as conn:
        cursor = conn.cursor()

        # 1. Edital: reaproveita se já existir (evita duplicar o mesmo concurso).
        cursor.execute("SELECT id FROM editais WHERE nome = ?", (concurso,))
        linha_edital = cursor.fetchone()

        if linha_edital:
            edital_id = linha_edital["id"]
        else:
            data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute(
                "INSERT INTO editais (nome, data_criacao) VALUES (?, ?)",
                (concurso, data_criacao),
            )
            edital_id = cursor.lastrowid

        resumo["edital_id"] = edital_id

        # 2. Matérias e Tópicos.
        for nome_materia, topicos in materias_json.items():
            if not isinstance(topicos, list):
                # Ignora entradas malformadas sem derrubar toda a importação.
                continue

            cursor.execute(
                "SELECT id FROM materias WHERE edital_id = ? AND nome = ?",
                (edital_id, nome_materia),
            )
            linha_materia = cursor.fetchone()

            if linha_materia:
                materia_id = linha_materia["id"]
            else:
                cursor.execute(
                    "INSERT INTO materias (edital_id, nome) VALUES (?, ?)",
                    (edital_id, nome_materia),
                )
                materia_id = cursor.lastrowid
                resumo["materias_inseridas"] += 1

            for nome_topico in topicos:
                nome_topico = str(nome_topico).strip()
                if not nome_topico:
                    continue

                cursor.execute(
                    "SELECT id FROM topicos WHERE materia_id = ? AND nome = ?",
                    (materia_id, nome_topico),
                )
                if cursor.fetchone():
                    resumo["topicos_ignorados_duplicados"] += 1
                    continue

                cursor.execute(
                    "INSERT INTO topicos (materia_id, nome, status) VALUES (?, ?, ?)",
                    (materia_id, nome_topico, "Não Iniciado"),
                )
                resumo["topicos_inseridos"] += 1

        cursor.close()

    return resumo


# ---------------------------------------------------------------------------
# CONSULTAS DE LEITURA (para a UI)
# ---------------------------------------------------------------------------

def listar_editais() -> List[sqlite3.Row]:
    """Retorna todos os editais cadastrados, ordenados pelo mais recente."""
    with conectar() as conn:
        cursor = conn.execute("SELECT id, nome, data_criacao FROM editais ORDER BY id DESC")
        return cursor.fetchall()


def obter_estrutura_edital(edital_id: int) -> List[Dict[str, Any]]:
    """
    Retorna a estrutura completa (matérias + tópicos) de um edital,
    já organizada em formato de árvore pronta para a UI:

        [
            {
                "id": 1,
                "nome": "Matéria 1",
                "topicos": [
                    {"id": 10, "nome": "Tópico A", "status": "Não Iniciado", "rendimento_simulados": 0.0},
                    ...
                ]
            },
            ...
        ]
    """
    with conectar() as conn:
        materias_cursor = conn.execute(
            "SELECT id, nome FROM materias WHERE edital_id = ? ORDER BY nome",
            (edital_id,),
        )
        materias = materias_cursor.fetchall()

        estrutura = []
        for materia in materias:
            topicos_cursor = conn.execute(
                """
                SELECT id, nome, status, rendimento_simulados
                FROM topicos
                WHERE materia_id = ?
                ORDER BY id
                """,
                (materia["id"],),
            )
            topicos = [dict(t) for t in topicos_cursor.fetchall()]

            estrutura.append({
                "id": materia["id"],
                "nome": materia["nome"],
                "topicos": topicos,
            })

        return estrutura


def atualizar_status_topico(topico_id: int, novo_status: str) -> None:
    """
    Atualiza o status de estudo de um tópico.
    Valores sugeridos: 'Não Iniciado', 'Visto', 'Revisado'.
    """
    with conectar() as conn:
        conn.execute(
            "UPDATE topicos SET status = ? WHERE id = ?",
            (novo_status, topico_id),
        )


def contar_estatisticas_edital(edital_id: int) -> Dict[str, int]:
    """
    Retorna estatísticas rápidas de progresso de um edital,
    úteis para exibição no Dashboard (Fase futura).
    """
    with conectar() as conn:
        total = conn.execute(
            """
            SELECT COUNT(*) as total FROM topicos t
            JOIN materias m ON t.materia_id = m.id
            WHERE m.edital_id = ?
            """,
            (edital_id,),
        ).fetchone()["total"]

        vistos = conn.execute(
            """
            SELECT COUNT(*) as total FROM topicos t
            JOIN materias m ON t.materia_id = m.id
            WHERE m.edital_id = ? AND t.status != 'Não Iniciado'
            """,
            (edital_id,),
        ).fetchone()["total"]

        return {"total_topicos": total, "topicos_vistos": vistos}


def obter_edital_por_id(edital_id: int) -> Optional[sqlite3.Row]:
    """Retorna os dados básicos (id, nome, data_criacao, caminho_pdf) de um único edital."""
    with conectar() as conn:
        cursor = conn.execute(
            "SELECT id, nome, data_criacao, caminho_pdf FROM editais WHERE id = ?", (edital_id,)
        )
        return cursor.fetchone()


def vincular_pdf_edital(edital_id: int, caminho_pdf: str) -> None:
    """
    Associa o caminho de um arquivo PDF (ex: o PDF oficial do edital) ao
    edital ativo. Não copia o arquivo — apenas guarda o caminho local
    selecionado pelo usuário no FilePicker.
    """
    with conectar() as conn:
        cursor = conn.execute("SELECT id FROM editais WHERE id = ?", (edital_id,))
        if cursor.fetchone() is None:
            raise ValueError("Edital não encontrado.")

        conn.execute(
            "UPDATE editais SET caminho_pdf = ? WHERE id = ?",
            (caminho_pdf, edital_id),
        )


def obter_pdf_edital(edital_id: int) -> Optional[str]:
    """Retorna o caminho do PDF vinculado ao edital, ou None se não houver."""
    with conectar() as conn:
        linha = conn.execute(
            "SELECT caminho_pdf FROM editais WHERE id = ?", (edital_id,)
        ).fetchone()
        return linha["caminho_pdf"] if linha else None


def desvincular_pdf_edital(edital_id: int) -> None:
    """
    Remove o vínculo do PDF ao edital (apenas o caminho salvo no banco —
    o arquivo em si não é apagado do disco, já que nunca foi copiado).
    """
    with conectar() as conn:
        conn.execute(
            "UPDATE editais SET caminho_pdf = NULL WHERE id = ?", (edital_id,)
        )


def deletar_edital(edital_id: int) -> None:
    """
    Remove um edital e TUDO que está vinculado a ele: matérias, tópicos,
    simulados, itens de cronograma e metas diárias (via ON DELETE CASCADE
    das foreign keys). Ação destrutiva e irreversível — a UI deve confirmar
    explicitamente com o usuário antes de chamar esta função.
    """
    with conectar() as conn:
        cursor = conn.execute("SELECT id FROM editais WHERE id = ?", (edital_id,))
        if cursor.fetchone() is None:
            raise ValueError("Edital não encontrado.")

        conn.execute("DELETE FROM editais WHERE id = ?", (edital_id,))


def obter_estatisticas_por_materia(edital_id: int) -> List[Dict[str, Any]]:
    """
    Retorna o 'raio-x' de desempenho do edital, agregado por matéria.
    Usado como insumo estruturado para o prompt enviado ao Gemini
    (ai_service.py) e para os cards/gráficos do Dashboard.

    Retorno:
        [
            {
                "materia": "Direito Administrativo",
                "total_topicos": 10,
                "topicos_vistos": 4,
                "topicos_nao_iniciados": 6,
                "percentual_concluido": 40.0,
                "rendimento_medio_simulados": 62.5
            },
            ...
        ]
    """
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT
                m.id AS materia_id,
                m.nome AS materia_nome,
                COUNT(t.id) AS total_topicos,
                SUM(CASE WHEN t.status != 'Não Iniciado' THEN 1 ELSE 0 END) AS topicos_vistos,
                COALESCE(AVG(t.rendimento_simulados), 0.0) AS rendimento_medio
            FROM materias m
            LEFT JOIN topicos t ON t.materia_id = m.id
            WHERE m.edital_id = ?
            GROUP BY m.id, m.nome
            ORDER BY m.nome
            """,
            (edital_id,),
        )
        linhas = cursor.fetchall()

        resultado = []
        for linha in linhas:
            total = linha["total_topicos"] or 0
            vistos = linha["topicos_vistos"] or 0
            percentual = round((vistos / total) * 100, 1) if total > 0 else 0.0

            resultado.append({
                "materia": linha["materia_nome"],
                "total_topicos": total,
                "topicos_vistos": vistos,
                "topicos_nao_iniciados": total - vistos,
                "percentual_concluido": percentual,
                "rendimento_medio_simulados": round(linha["rendimento_medio"], 1),
            })

        return resultado


# ---------------------------------------------------------------------------
# SIMULADOS / TREINO DE QUESTÕES
# ---------------------------------------------------------------------------

def registrar_desempenho_simulado(
    edital_id: int,
    materia_id: int,
    topico_id: Optional[int],
    total: int,
    acertos: int,
) -> None:
    """
    Registra uma sessão de questões feitas pelo usuário (ex: "20 questões,
    14 acertos") na tabela `simulados` e recalcula o `rendimento_simulados`
    do tópico correspondente.

    O `rendimento_simulados` salvo em `topicos` é a MÉDIA PONDERADA (acertos
    totais / questões totais) de TODAS as sessões já registradas para aquele
    tópico — não apenas a última — para refletir a evolução real do usuário
    e não apenas o resultado mais recente.

    Lança:
        ValueError: se `total` for <= 0 ou `acertos` estiver fora do
        intervalo [0, total].
    """
    if total <= 0:
        raise ValueError("O total de questões deve ser maior que zero.")
    if acertos < 0 or acertos > total:
        raise ValueError("O número de acertos deve estar entre 0 e o total de questões.")

    data_registro = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with conectar() as conn:
        conn.execute(
            """
            INSERT INTO simulados (edital_id, data, total_questoes, acertos, materia_id, topico_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (edital_id, data_registro, total, acertos, materia_id, topico_id),
        )

        if topico_id is not None:
            linha = conn.execute(
                """
                SELECT SUM(total_questoes) AS soma_total, SUM(acertos) AS soma_acertos
                FROM simulados
                WHERE topico_id = ?
                """,
                (topico_id,),
            ).fetchone()

            soma_total = linha["soma_total"] or 0
            soma_acertos = linha["soma_acertos"] or 0
            novo_rendimento = round((soma_acertos / soma_total) * 100, 1) if soma_total > 0 else 0.0

            conn.execute(
                "UPDATE topicos SET rendimento_simulados = ? WHERE id = ?",
                (novo_rendimento, topico_id),
            )


def obter_historico_desempenho(edital_id: int) -> Dict[str, Any]:
    """
    Retorna a evolução do desempenho em questões/simulados de um edital,
    pronta para alimentar o Dashboard e o prompt do Gemini (ai_service.py).

    Retorno:
        {
            "evolucao": [
                {
                    "data": "2026-07-04 10:30:00",
                    "materia": "Direito Administrativo",
                    "topico": "Atos Administrativos",  # ou None (registro genérico da matéria)
                    "total_questoes": 20,
                    "acertos": 14,
                    "percentual": 70.0
                },
                ...
            ],  # ordenado da sessão mais antiga para a mais recente
            "materias_criticas": [
                {
                    "materia": "Raciocínio Lógico",
                    "total_questoes": 50,
                    "acertos": 22,
                    "percentual_acertos": 44.0
                },
                ...
            ]  # ordenado do PIOR para o MELHOR desempenho (percentual crescente)
        }
    """
    with conectar() as conn:
        linhas_evolucao = conn.execute(
            """
            SELECT
                s.data AS data,
                m.nome AS materia,
                t.nome AS topico,
                s.total_questoes AS total_questoes,
                s.acertos AS acertos
            FROM simulados s
            JOIN materias m ON s.materia_id = m.id
            LEFT JOIN topicos t ON s.topico_id = t.id
            WHERE s.edital_id = ?
            ORDER BY s.data ASC
            """,
            (edital_id,),
        ).fetchall()

        evolucao = []
        for linha in linhas_evolucao:
            total = linha["total_questoes"]
            acertos = linha["acertos"]
            percentual = round((acertos / total) * 100, 1) if total > 0 else 0.0
            evolucao.append({
                "data": linha["data"],
                "materia": linha["materia"],
                "topico": linha["topico"],
                "total_questoes": total,
                "acertos": acertos,
                "percentual": percentual,
            })

        linhas_materias = conn.execute(
            """
            SELECT
                m.nome AS materia,
                SUM(s.total_questoes) AS total_questoes,
                SUM(s.acertos) AS acertos
            FROM simulados s
            JOIN materias m ON s.materia_id = m.id
            WHERE s.edital_id = ?
            GROUP BY m.id, m.nome
            """,
            (edital_id,),
        ).fetchall()

        materias_criticas = []
        for linha in linhas_materias:
            total = linha["total_questoes"] or 0
            acertos = linha["acertos"] or 0
            percentual = round((acertos / total) * 100, 1) if total > 0 else 0.0
            materias_criticas.append({
                "materia": linha["materia"],
                "total_questoes": total,
                "acertos": acertos,
                "percentual_acertos": percentual,
            })

        # Ordena da matéria com PIOR desempenho para a com MELHOR desempenho,
        # para destacar imediatamente onde o usuário mais precisa de atenção.
        materias_criticas.sort(key=lambda m: m["percentual_acertos"])

        return {"evolucao": evolucao, "materias_criticas": materias_criticas}


# ---------------------------------------------------------------------------
# CONFIGURAÇÃO DA PROVA (data + capacidade diária de estudo)
# ---------------------------------------------------------------------------

def atualizar_config_prova(
    edital_id: int,
    data_prova: Optional[str],
    capacidade_diaria_min: int,
) -> None:
    """
    Define a data da prova (formato 'YYYY-MM-DD', ou None para remover) e a
    capacidade diária de estudo (em minutos) de um edital. Usadas pelo
    algoritmo de geração de cronograma.
    """

    if capacidade_diaria_min <= 0:
        raise ValueError("A capacidade diária de estudo deve ser maior que zero.")

    with conectar() as conn:
        conn.execute(
            "UPDATE editais SET data_prova = ?, capacidade_diaria_min = ? WHERE id = ?",
            (data_prova, capacidade_diaria_min, edital_id),
        )


def obter_config_prova(edital_id: int) -> Dict[str, Any]:
    """Retorna a data da prova e a capacidade diária configuradas para o edital."""

    with conectar() as conn:
        linha = conn.execute(
            "SELECT data_prova, capacidade_diaria_min FROM editais WHERE id = ?",
            (edital_id,),
        ).fetchone()

        if linha is None:
            return {"data_prova": None, "capacidade_diaria_min": 120}

        return {
            "data_prova": linha["data_prova"],
            "capacidade_diaria_min": linha["capacidade_diaria_min"] or 120,
        }


def calcular_dias_restantes_prova(edital_id: int) -> Optional[int]:
    """Retorna quantos dias faltam para a prova, ou None se a data não foi definida."""

    config = obter_config_prova(edital_id)
    if not config["data_prova"]:
        return None

    data_prova = datetime.strptime(config["data_prova"], "%Y-%m-%d").date()
    return (data_prova - datetime.now().date()).days


# ---------------------------------------------------------------------------
# META DIÁRIA DE QUESTÕES
# ---------------------------------------------------------------------------

def definir_meta_diaria(edital_id: int, data: str, meta_questoes: int) -> None:
    """
    Define (ou atualiza) a meta de questões de um dia específico
    ('YYYY-MM-DD') para um edital.
    """

    if meta_questoes <= 0:
        raise ValueError("A meta de questões deve ser maior que zero.")

    with conectar() as conn:
        conn.execute(
            """
            INSERT INTO meta_questoes_diaria (edital_id, data, meta_questoes)
            VALUES (?, ?, ?)
            ON CONFLICT(edital_id, data) DO UPDATE SET meta_questoes = excluded.meta_questoes
            """,
            (edital_id, data, meta_questoes),
        )


def _questoes_feitas_no_dia(conn: sqlite3.Connection, edital_id: int, data: str) -> int:
    """Soma o total de questões registradas em `simulados` num dia específico."""

    linha = conn.execute(
        """
        SELECT COALESCE(SUM(total_questoes), 0) AS total
        FROM simulados
        WHERE edital_id = ? AND date(data) = ?
        """,
        (edital_id, data),
    ).fetchone()

    return linha["total"]


def obter_meta_diaria(edital_id: int, data: str) -> Dict[str, Any]:
    """
    Retorna a meta de questões de um dia e quantas já foram feitas
    (calculado a partir de `simulados`, nunca fica dessincronizado).
    """

    with conectar() as conn:
        linha = conn.execute(
            "SELECT meta_questoes FROM meta_questoes_diaria WHERE edital_id = ? AND data = ?",
            (edital_id, data),
        ).fetchone()

        meta = linha["meta_questoes"] if linha else 0
        feitas = _questoes_feitas_no_dia(conn, edital_id, data)
        percentual = round((feitas / meta) * 100, 1) if meta > 0 else 0.0

        return {"meta_questoes": meta, "questoes_feitas": feitas, "percentual": percentual}


def calcular_streak_meta_diaria(edital_id: int) -> int:
    """
    Calcula quantos dias seguidos a meta de questões foi batida, terminando
    hoje (se já batida) ou ontem (se hoje ainda está em aberto). Um dia sem
    meta definida interrompe a contagem.
    """

    with conectar() as conn:

        def meta_foi_batida(data_str: str) -> Optional[bool]:
            linha = conn.execute(
                "SELECT meta_questoes FROM meta_questoes_diaria WHERE edital_id = ? AND data = ?",
                (edital_id, data_str),
            ).fetchone()
            if linha is None or linha["meta_questoes"] <= 0:
                return None
            feitas = _questoes_feitas_no_dia(conn, edital_id, data_str)
            return feitas >= linha["meta_questoes"]

        hoje = datetime.now().date()
        streak = 0
        dia = hoje

        if meta_foi_batida(hoje.strftime("%Y-%m-%d")) is True:
            streak = 1
        dia = hoje - timedelta(days=1)

        while meta_foi_batida(dia.strftime("%Y-%m-%d")) is True:
            streak += 1
            dia -= timedelta(days=1)

        return streak


# ---------------------------------------------------------------------------
# CRONOGRAMA DE ESTUDOS (plano dia a dia, priorizado pelo desempenho)
# ---------------------------------------------------------------------------

STATUS_CRONOGRAMA_PENDENTE = "Pendente"
STATUS_CRONOGRAMA_CONCLUIDO = "Concluído"
STATUS_CRONOGRAMA_PULADO = "Pulado"


def gerar_cronograma(edital_id: int) -> int:
    """
    Gera o cronograma dia a dia entre hoje e a data da prova, priorizando
    tópicos com pior desempenho (ou ainda não iniciados). Regras de peso:

        - Não Iniciado                    -> peso 3, atividade 'Teoria'
        - Visto, rendimento < 60%          -> peso 3, atividade 'Questões'
        - Visto, rendimento entre 60-80%   -> peso 2, atividade 'Questões'
        - Visto, rendimento >= 80%         -> peso 1, atividade 'Revisão'

    Os itens são intercalados entre os tópicos (round-robin) para não
    empilhar o mesmo tópico em dias seguidos, e distribuídos respeitando a
    capacidade diária de estudo (`capacidade_diaria_min`).

    Reexecutar esta função REMOVE e recria apenas os itens futuros ainda
    'Pendente' — dias passados e itens já concluídos/pulados são
    preservados como histórico.

    Retorna o número de itens gerados.
    """

    config = obter_config_prova(edital_id)
    if not config["data_prova"]:
        raise ValueError("Defina a data da prova antes de gerar o cronograma.")

    hoje = datetime.now().date()
    data_prova = datetime.strptime(config["data_prova"], "%Y-%m-%d").date()
    dias_restantes = (data_prova - hoje).days

    if dias_restantes <= 0:
        raise ValueError("A data da prova já passou ou é hoje — ajuste a data da prova.")

    capacidade = config["capacidade_diaria_min"] or 120

    with conectar() as conn:
        hoje_str = hoje.strftime("%Y-%m-%d")
        conn.execute(
            "DELETE FROM cronograma_estudos WHERE edital_id = ? AND data >= ? AND status = ?",
            (edital_id, hoje_str, STATUS_CRONOGRAMA_PENDENTE),
        )

        materias = conn.execute(
            "SELECT id, nome FROM materias WHERE edital_id = ? ORDER BY nome",
            (edital_id,),
        ).fetchall()

        grupos_por_topico = []
        for materia in materias:
            topicos = conn.execute(
                """
                SELECT id, nome, status, rendimento_simulados
                FROM topicos WHERE materia_id = ? ORDER BY id
                """,
                (materia["id"],),
            ).fetchall()

            for topico in topicos:
                rendimento = topico["rendimento_simulados"] or 0.0

                if topico["status"] == "Não Iniciado":
                    peso, tipo, tempo = 3, "Teoria", 45
                elif rendimento < 60:
                    peso, tipo, tempo = 3, "Questões", 30
                elif rendimento < 80:
                    peso, tipo, tempo = 2, "Questões", 25
                else:
                    peso, tipo, tempo = 1, "Revisão", 20

                item_base = {
                    "materia_id": materia["id"],
                    "topico_id": topico["id"],
                    "tipo_atividade": tipo,
                    "tempo_estimado_min": tempo,
                }
                grupos_por_topico.append([item_base] * peso)

        if not grupos_por_topico:
            raise ValueError("Nenhum tópico cadastrado para este edital.")

        # Intercala os grupos (round-robin) para não repetir o mesmo tópico
        # em sequência: pega um item de cada grupo por vez, em rodadas.
        fila = [
            item
            for rodada in itertools.zip_longest(*grupos_por_topico)
            for item in rodada
            if item is not None
        ]

        total_itens = 0
        carga_por_dia = [0] * dias_restantes

        for item in fila:
            # Prefere o dia menos carregado que ainda cabe dentro da
            # capacidade diária; se nenhum couber (demanda > capacidade
            # total disponível), usa o dia menos carregado mesmo assim —
            # isso distribui o excedente de forma equilibrada entre os
            # dias, em vez de empilhar tudo no último dia.
            candidatos = [
                d for d in range(dias_restantes)
                if carga_por_dia[d] + item["tempo_estimado_min"] <= capacidade
            ]
            dia_escolhido = min(
                candidatos or range(dias_restantes),
                key=lambda d: carga_por_dia[d],
            )

            data_item = (hoje + timedelta(days=dia_escolhido)).strftime("%Y-%m-%d")

            conn.execute(
                """
                INSERT INTO cronograma_estudos
                (edital_id, materia_id, topico_id, data, tipo_atividade, tempo_estimado_min, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edital_id,
                    item["materia_id"],
                    item["topico_id"],
                    data_item,
                    item["tipo_atividade"],
                    item["tempo_estimado_min"],
                    STATUS_CRONOGRAMA_PENDENTE,
                ),
            )
            carga_por_dia[dia_escolhido] += item["tempo_estimado_min"]
            total_itens += 1

        return total_itens


def listar_cronograma_periodo(
    edital_id: int, data_inicio: str, data_fim: str,
) -> List[Dict[str, Any]]:
    """Lista os itens do cronograma de um edital dentro de um período (inclusive)."""

    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT c.*, m.nome AS materia_nome, t.nome AS topico_nome
            FROM cronograma_estudos c
            JOIN materias m ON m.id = c.materia_id
            LEFT JOIN topicos t ON t.id = c.topico_id
            WHERE c.edital_id = ? AND c.data BETWEEN ? AND ?
            ORDER BY c.data, c.id
            """,
            (edital_id, data_inicio, data_fim),
        )
        return [dict(linha) for linha in cursor.fetchall()]


def atualizar_item_cronograma(
    item_id: int,
    status: Optional[str] = None,
    fonte_estudo: Optional[str] = None,
    notas: Optional[str] = None,
) -> None:
    """Atualiza status/fonte de estudo/notas de um item do cronograma."""

    with conectar() as conn:
        item = conn.execute(
            "SELECT * FROM cronograma_estudos WHERE id = ?", (item_id,),
        ).fetchone()

        if item is None:
            raise ValueError("Item de cronograma não encontrado.")

        conn.execute(
            """
            UPDATE cronograma_estudos
            SET status = ?, fonte_estudo = ?, notas = ?
            WHERE id = ?
            """,
            (
                status if status is not None else item["status"],
                fonte_estudo if fonte_estudo is not None else item["fonte_estudo"],
                notas if notas is not None else item["notas"],
                item_id,
            ),
        )


# ---------------------------------------------------------------------------
# MÓDULO FACULDADE (disciplinas, faltas e notas)
# ---------------------------------------------------------------------------

def inserir_disciplina(nome: str, professor: str = "") -> int:
    """Cadastra uma nova disciplina da faculdade. Retorna o id gerado."""
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO faculdade_materias (nome, professor) VALUES (?, ?)",
            (nome.strip(), (professor or "").strip()),
        )
        return cursor.lastrowid


def listar_disciplinas() -> List[Dict[str, Any]]:
    """Retorna todas as disciplinas cadastradas, ordenadas por nome."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT id, nome, professor, faltas, m1, m2, media_final
            FROM faculdade_materias
            ORDER BY nome
            """
        )
        return [dict(linha) for linha in cursor.fetchall()]


def atualizar_faltas_disciplina(disciplina_id: int, delta: int) -> int:
    """
    Incrementa (delta=+1) ou decrementa (delta=-1) o contador de faltas de
    uma disciplina. O valor nunca fica negativo. Retorna o novo total de faltas.
    """
    with conectar() as conn:
        linha = conn.execute(
            "SELECT faltas FROM faculdade_materias WHERE id = ?", (disciplina_id,)
        ).fetchone()
        if linha is None:
            raise ValueError("Disciplina não encontrada.")

        novo_valor = max(0, linha["faltas"] + delta)
        conn.execute(
            "UPDATE faculdade_materias SET faltas = ? WHERE id = ?",
            (novo_valor, disciplina_id),
        )
        return novo_valor


def atualizar_notas_disciplina(disciplina_id: int, m1: float, m2: float) -> float:
    """
    Atualiza as notas M1/M2 de uma disciplina e recalcula automaticamente a
    `media_final` (média aritmética simples entre M1 e M2). Retorna a nova média.
    """
    media_final = round((m1 + m2) / 2, 2)
    with conectar() as conn:
        conn.execute(
            "UPDATE faculdade_materias SET m1 = ?, m2 = ?, media_final = ? WHERE id = ?",
            (m1, m2, media_final, disciplina_id),
        )
    return media_final


def deletar_disciplina(disciplina_id: int) -> None:
    """Remove uma disciplina cadastrada."""
    with conectar() as conn:
        conn.execute("DELETE FROM faculdade_materias WHERE id = ?", (disciplina_id,))


# ---------------------------------------------------------------------------
# MÓDULO CLIENTES & FREELAS (projetos)
# ---------------------------------------------------------------------------

STATUS_PROJETO_PADRAO = "Em Andamento"

def inserir_projeto(
    nome_projeto: str,
    cliente: str = "",
    prazo: str = "",
    valor: float = 0.0,
    status: str = STATUS_PROJETO_PADRAO,
    entregas: str = "",
) -> int:
    """Cadastra um novo projeto/freela. Retorna o id gerado."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO clientes_projetos (nome_projeto, cliente, prazo, valor, status, entregas)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (nome_projeto.strip(), (cliente or "").strip(), (prazo or "").strip(), valor, status, entregas or ""),
        )
        return cursor.lastrowid


def listar_projetos() -> List[Dict[str, Any]]:
    """Retorna todos os projetos cadastrados, ordenados pelo mais recente."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT id, nome_projeto, cliente, prazo, valor, status, entregas
            FROM clientes_projetos
            ORDER BY id DESC
            """
        )
        return [dict(linha) for linha in cursor.fetchall()]


def atualizar_status_projeto(projeto_id: int, novo_status: str) -> None:
    """Atualiza apenas o status de um projeto (usado pelo Dropdown rápido da UI)."""
    with conectar() as conn:
        conn.execute(
            "UPDATE clientes_projetos SET status = ? WHERE id = ?",
            (novo_status, projeto_id),
        )


def atualizar_projeto(
    projeto_id: int,
    nome_projeto: Optional[str] = None,
    cliente: Optional[str] = None,
    prazo: Optional[str] = None,
    valor: Optional[float] = None,
    status: Optional[str] = None,
    entregas: Optional[str] = None,
) -> None:
    """
    Atualiza os campos informados (não-None) de um projeto. Útil para telas
    de edição futuras sem precisar reescrever o registro inteiro.
    """
    campos = {
        "nome_projeto": nome_projeto,
        "cliente": cliente,
        "prazo": prazo,
        "valor": valor,
        "status": status,
        "entregas": entregas,
    }
    campos_informados = {k: v for k, v in campos.items() if v is not None}
    if not campos_informados:
        return

    colunas_set = ", ".join(f"{coluna} = ?" for coluna in campos_informados)
    valores = list(campos_informados.values()) + [projeto_id]

    with conectar() as conn:
        conn.execute(f"UPDATE clientes_projetos SET {colunas_set} WHERE id = ?", valores)


def deletar_projeto(projeto_id: int) -> None:
    """Remove um projeto/freela cadastrado."""
    with conectar() as conn:
        conn.execute("DELETE FROM clientes_projetos WHERE id = ?", (projeto_id,))


# ---------------------------------------------------------------------------
# MÓDULO ROTINA & HÁBITOS
# ---------------------------------------------------------------------------

DIAS_SEMANA_ROTINA = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]

def inserir_habito(nome_habito: str, horario: Optional[str] = None) -> int:
    """Cadastra um novo hábito (todos os dias começam desmarcados). Retorna o id gerado."""
    with conectar() as conn:
        cursor = conn.execute(
            "INSERT INTO rotina_habitos (nome_habito, horario) VALUES (?, ?)",
            (nome_habito.strip(), (horario or "").strip() or None),
        )
        return cursor.lastrowid


def listar_habitos() -> List[Dict[str, Any]]:
    """Retorna todos os hábitos cadastrados, com o status de cada dia da semana."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT id, nome_habito, horario, segunda, terca, quarta, quinta, sexta, sabado, domingo
            FROM rotina_habitos
            ORDER BY (horario IS NULL), horario, id
            """
        )
        return [dict(linha) for linha in cursor.fetchall()]


def atualizar_horario_habito(habito_id: int, horario: Optional[str]) -> None:
    """Define (ou remove, se `horario` for None/vazio) o horário sugerido de um hábito."""
    with conectar() as conn:
        conn.execute(
            "UPDATE rotina_habitos SET horario = ? WHERE id = ?",
            ((horario or "").strip() or None, habito_id),
        )


def atualizar_dia_habito(habito_id: int, dia: str, valor: bool) -> None:
    """
    Marca (True) ou desmarca (False) um hábito em um dia específico da semana.

    Lança:
        ValueError: se `dia` não for um dos dias válidos (segunda..domingo).
    """
    if dia not in DIAS_SEMANA_ROTINA:
        raise ValueError(
            f"Dia inválido: '{dia}'. Use um de: {', '.join(DIAS_SEMANA_ROTINA)}."
        )

    with conectar() as conn:
        conn.execute(
            f"UPDATE rotina_habitos SET {dia} = ? WHERE id = ?",
            (1 if valor else 0, habito_id),
        )


def deletar_habito(habito_id: int) -> None:
    """Remove um hábito cadastrado."""
    with conectar() as conn:
        conn.execute("DELETE FROM rotina_habitos WHERE id = ?", (habito_id,))


# ---------------------------------------------------------------------------
# MÓDULO ROTINA & HÁBITOS — Tarefas (planejadas e extras/imprevistos)
# ---------------------------------------------------------------------------

PRIORIDADE_ALTA = "Alta"
PRIORIDADE_MEDIA = "Média"
PRIORIDADE_BAIXA = "Baixa"

STATUS_TAREFA_PENDENTE = "Pendente"
STATUS_TAREFA_CONCLUIDA = "Concluída"

ORIGEM_TAREFA_PLANEJADA = "Planejada"
ORIGEM_TAREFA_EXTRA = "Extra"


def adicionar_tarefa(
    titulo: str,
    descricao: str = "",
    data: Optional[str] = None,
    horario: Optional[str] = None,
    prioridade: str = PRIORIDADE_MEDIA,
    origem: str = ORIGEM_TAREFA_PLANEJADA,
) -> int:
    """
    Cadastra uma tarefa avulsa. `data`/`horario` são opcionais (tarefa sem
    prazo definido fica no backlog). `origem` distingue tarefas planejadas
    de atividades extras/imprevistos que surgiram no meio do dia.
    """

    titulo = (titulo or "").strip()
    if not titulo:
        raise ValueError("Informe o título da tarefa.")

    if prioridade not in (PRIORIDADE_ALTA, PRIORIDADE_MEDIA, PRIORIDADE_BAIXA):
        raise ValueError("Prioridade inválida.")

    if origem not in (ORIGEM_TAREFA_PLANEJADA, ORIGEM_TAREFA_EXTRA):
        raise ValueError("Origem inválida.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tarefas (titulo, descricao, data, horario, prioridade, status, origem)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                titulo,
                (descricao or "").strip(),
                (data or "").strip() or None,
                (horario or "").strip() or None,
                prioridade,
                STATUS_TAREFA_PENDENTE,
                origem,
            ),
        )
        return cursor.lastrowid


def listar_tarefas(
    origem: Optional[str] = None,
    incluir_concluidas: bool = True,
) -> List[Dict[str, Any]]:
    """
    Lista tarefas, opcionalmente filtradas por origem ('Planejada'/'Extra').
    Ordenadas por: pendentes primeiro, depois por data/horário (tarefas sem
    data vão para o fim) e por prioridade (Alta > Média > Baixa).
    """

    condicoes = []
    parametros: List[Any] = []

    if origem is not None:
        condicoes.append("origem = ?")
        parametros.append(origem)

    if not incluir_concluidas:
        condicoes.append("status != ?")
        parametros.append(STATUS_TAREFA_CONCLUIDA)

    where_sql = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""

    with conectar() as conn:
        cursor = conn.execute(
            f"""
            SELECT * FROM tarefas
            {where_sql}
            ORDER BY
                (status = '{STATUS_TAREFA_CONCLUIDA}'),
                (data IS NULL), data,
                (horario IS NULL), horario,
                CASE prioridade
                    WHEN '{PRIORIDADE_ALTA}' THEN 0
                    WHEN '{PRIORIDADE_MEDIA}' THEN 1
                    ELSE 2
                END,
                id
            """,
            parametros,
        )
        return [dict(linha) for linha in cursor.fetchall()]


def alternar_status_tarefa(tarefa_id: int, concluida: bool) -> None:
    """Marca/desmarca uma tarefa como concluída."""
    with conectar() as conn:
        conn.execute(
            "UPDATE tarefas SET status = ? WHERE id = ?",
            (STATUS_TAREFA_CONCLUIDA if concluida else STATUS_TAREFA_PENDENTE, tarefa_id),
        )


def deletar_tarefa(tarefa_id: int) -> None:
    """Remove uma tarefa."""
    with conectar() as conn:
        conn.execute("DELETE FROM tarefas WHERE id = ?", (tarefa_id,))


# ---------------------------------------------------------------------------
# MÓDULO FINANCEIRO (boletos mensais)
# ---------------------------------------------------------------------------

STATUS_BOLETO_PENDENTE = "Pendente"
STATUS_BOLETO_PAGO = "Pago"


def adicionar_boleto(
    nome: str, valor: float, data_vencimento: str, codigo_barras: str = ""
) -> int:
    """
    Cadastra um novo boleto (sempre como 'Pendente'). Retorna o id gerado.

    Parâmetros:
        nome: descrição do boleto (ex: "Energia - Enel").
        valor: valor em reais (ex: 189.90).
        data_vencimento: data no formato ISO 'YYYY-MM-DD' (ex: '2026-07-15').
        codigo_barras: linha digitável ou código "copia e cola" do boleto/PIX.

    Lança:
        ValueError: se `nome` estiver vazio ou `valor` não for positivo.
    """
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe o nome do boleto.")
    if valor is None or valor <= 0:
        raise ValueError("O valor do boleto deve ser maior que zero.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO boletos (nome, valor, data_vencimento, codigo_barras, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nome, valor, data_vencimento, (codigo_barras or "").strip(), STATUS_BOLETO_PENDENTE),
        )
        return cursor.lastrowid


def listar_boletos_mes(ano_mes: str) -> List[Dict[str, Any]]:
    """
    Retorna todos os boletos cujo vencimento cai no mês informado, ordenados
    por data de vencimento (do mais próximo ao mais distante).

    Parâmetros:
        ano_mes: string no formato 'YYYY-MM' (ex: '2026-07').
    """
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT id, nome, valor, data_vencimento, codigo_barras, status
            FROM boletos
            WHERE data_vencimento LIKE ?
            ORDER BY data_vencimento ASC
            """,
            (f"{ano_mes}%",),
        )
        return [dict(linha) for linha in cursor.fetchall()]


def alterar_status_boleto(boleto_id: int, novo_status: str) -> None:
    """Atualiza o status de um boleto (ex: 'Pendente' <-> 'Pago')."""
    with conectar() as conn:
        conn.execute(
            "UPDATE boletos SET status = ? WHERE id = ?",
            (novo_status, boleto_id),
        )


def deletar_boleto(boleto_id: int) -> None:
    """Remove um boleto cadastrado."""
    with conectar() as conn:
        conn.execute("DELETE FROM boletos WHERE id = ?", (boleto_id,))


# ---------------------------------------------------------------------------
# MÓDULO FINANCEIRO
# Fluxo de Caixa (Receitas / Despesas Variáveis)
# ---------------------------------------------------------------------------

TIPO_TRANSACAO_RECEITA = "Receita"
TIPO_TRANSACAO_DESPESA = "Despesa_Variavel"


def adicionar_transacao(
    descricao: str,
    valor: float,
    tipo: str,
    categoria: str,
    data: str,
) -> int:
    """
    Cadastra uma transação financeira.

    tipo:
        Receita
        Despesa_Variavel

    Retorna o ID criado.
    """

    descricao = (descricao or "").strip()
    categoria = (categoria or "").strip()

    if not descricao:
        raise ValueError("Informe a descrição da transação.")

    if valor is None or valor <= 0:
        raise ValueError("O valor deve ser maior que zero.")

    if tipo not in (
        TIPO_TRANSACAO_RECEITA,
        TIPO_TRANSACAO_DESPESA,
    ):
        raise ValueError("Tipo de transação inválido.")

    if not categoria:
        raise ValueError("Informe a categoria.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO transacoes
            (
                descricao,
                valor,
                tipo,
                categoria,
                data
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                descricao,
                valor,
                tipo,
                categoria,
                data,
            ),
        )

        return cursor.lastrowid


def listar_transacoes_mes(
    ano_mes: str,
) -> List[Dict[str, Any]]:
    """
    Lista todas as transações do mês.

    Exemplo:
        2026-07
    """

    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT
                id,
                descricao,
                valor,
                tipo,
                categoria,
                data
            FROM transacoes
            WHERE data LIKE ?
            ORDER BY data ASC, id DESC
            """,
            (f"{ano_mes}%",),
        )

        return [dict(linha) for linha in cursor.fetchall()]


def deletar_transacao(
    transacao_id: int,
) -> None:
    """
    Remove uma transação.
    """

    with conectar() as conn:
        conn.execute(
            """
            DELETE FROM transacoes
            WHERE id = ?
            """,
            (transacao_id,),
        )


# ---------------------------------------------------------------------------
# MÓDULO FINANCEIRO
# Metas de Investimento / Poupança
# ---------------------------------------------------------------------------


def adicionar_meta(
    nome_meta: str,
    valor_alvo: float,
    valor_atual: float = 0.0,
) -> int:
    """
    Cadastra uma meta financeira.
    """

    nome_meta = (nome_meta or "").strip()

    if not nome_meta:
        raise ValueError("Informe o nome da meta.")

    if valor_alvo <= 0:
        raise ValueError("O valor alvo deve ser maior que zero.")

    if valor_atual < 0:
        raise ValueError("O valor atual não pode ser negativo.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO metas_investimento
            (
                nome_meta,
                valor_alvo,
                valor_atual
            )
            VALUES (?, ?, ?)
            """,
            (
                nome_meta,
                valor_alvo,
                valor_atual,
            ),
        )

        return cursor.lastrowid


def listar_metas() -> List[Dict[str, Any]]:
    """
    Lista todas as metas cadastradas.
    """

    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT
                id,
                nome_meta,
                valor_alvo,
                valor_atual
            FROM metas_investimento
            ORDER BY nome_meta
            """
        )

        return [dict(linha) for linha in cursor.fetchall()]


def atualizar_saldo_meta(
    meta_id: int,
    novo_valor_atual: float,
) -> None:
    """
    Atualiza o saldo acumulado da meta.
    """

    if novo_valor_atual < 0:
        novo_valor_atual = 0.0

    with conectar() as conn:
        conn.execute(
            """
            UPDATE metas_investimento
            SET valor_atual = ?
            WHERE id = ?
            """,
            (
                novo_valor_atual,
                meta_id,
            ),
        )


def deletar_meta(
    meta_id: int,
) -> None:
    """
    Remove uma meta.
    """

    with conectar() as conn:
        conn.execute(
            """
            DELETE FROM metas_investimento
            WHERE id = ?
            """,
            (meta_id,),
        )

# ---------------------------------------------------------------------------
# MÓDULO FINANCEIRO
# Empréstimos
# ---------------------------------------------------------------------------

MODALIDADE_BULLET = "bullet"
MODALIDADE_CARENCIA = "carencia"
MODALIDADE_PARCELADO = "parcelado"

STATUS_EMPRESTIMO_ATIVO = "ativo"
STATUS_EMPRESTIMO_QUITADO = "quitado"

STATUS_PARCELA_PENDENTE = "pendente"
STATUS_PARCELA_PAGO = "pago"
STATUS_PARCELA_ATRASADO = "atrasado"


def adicionar_cliente_emprestimo(
    nome: str,
    contato: str = "",
    observacoes: str = "",
) -> int:
    """
    Cadastra um cliente de empréstimo.
    """

    nome = (nome or "").strip()

    if not nome:
        raise ValueError("Informe o nome do cliente.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO clientes_emprestimo (nome, contato, observacoes)
            VALUES (?, ?, ?)
            """,
            (nome, (contato or "").strip(), (observacoes or "").strip()),
        )

        return cursor.lastrowid


def listar_clientes_emprestimo() -> List[Dict[str, Any]]:
    """
    Lista todos os clientes de empréstimo cadastrados.
    """

    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT id, nome, contato, observacoes
            FROM clientes_emprestimo
            ORDER BY nome
            """
        )

        return [dict(linha) for linha in cursor.fetchall()]


def criar_emprestimo(
    cliente_id: int,
    valor_principal: float,
    taxa_juros_mensal: float,
    modalidade: str,
    valor_parcela_principal: Optional[float] = None,
    data_inicio: Optional[str] = None,
) -> int:
    """
    Cria um novo empréstimo e já gera a primeira parcela conforme a
    modalidade escolhida:

        - bullet:     1 parcela em 30 dias com principal + juros integrais.
        - carencia:   1ª parcela em 30 dias, somente juros (o principal é
                      quitado depois, via `gerar_proxima_parcela`).
        - parcelado:  1ª parcela em 30 dias com juros + a fatia de
                      `valor_parcela_principal` do principal.

    O juro é sempre calculado sobre o valor_principal ORIGINAL do
    empréstimo (juros fixos), nunca sobre o saldo devedor.
    """

    if valor_principal <= 0:
        raise ValueError("O valor principal deve ser maior que zero.")

    if taxa_juros_mensal <= 0:
        raise ValueError("A taxa de juros deve ser maior que zero.")

    if modalidade not in (MODALIDADE_BULLET, MODALIDADE_CARENCIA, MODALIDADE_PARCELADO):
        raise ValueError("Modalidade de empréstimo inválida.")

    if modalidade == MODALIDADE_PARCELADO and not valor_parcela_principal:
        raise ValueError("Informe o valor da parcela de principal para a modalidade parcelada.")

    data_inicio = data_inicio or datetime.now().strftime("%Y-%m-%d")
    data_primeiro_vencimento = (
        datetime.strptime(data_inicio, "%Y-%m-%d") + timedelta(days=30)
    ).strftime("%Y-%m-%d")

    valor_juros_fixo = valor_principal * taxa_juros_mensal

    if modalidade == MODALIDADE_BULLET:
        principal_primeira_parcela = valor_principal
    elif modalidade == MODALIDADE_PARCELADO:
        principal_primeira_parcela = min(valor_parcela_principal, valor_principal)
    else:  # carência
        principal_primeira_parcela = 0.0

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO emprestimos
            (
                cliente_id,
                valor_principal,
                taxa_juros_mensal,
                modalidade,
                valor_parcela_principal,
                data_inicio,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cliente_id,
                valor_principal,
                taxa_juros_mensal,
                modalidade,
                valor_parcela_principal,
                data_inicio,
                STATUS_EMPRESTIMO_ATIVO,
            ),
        )
        emprestimo_id = cursor.lastrowid

        conn.execute(
            """
            INSERT INTO parcelas_emprestimo
            (emprestimo_id, numero, valor_juros, valor_principal, data_vencimento, status)
            VALUES (?, 1, ?, ?, ?, ?)
            """,
            (
                emprestimo_id,
                valor_juros_fixo,
                principal_primeira_parcela,
                data_primeiro_vencimento,
                STATUS_PARCELA_PENDENTE,
            ),
        )

        return emprestimo_id


def _saldo_devedor_emprestimo(conn: sqlite3.Connection, emprestimo_id: int) -> float:
    """
    Calcula o saldo devedor de principal de um empréstimo:
    valor_principal original - soma do principal já pago nas parcelas.
    """

    linha = conn.execute(
        "SELECT valor_principal FROM emprestimos WHERE id = ?",
        (emprestimo_id,),
    ).fetchone()

    if linha is None:
        return 0.0

    principal_original = linha["valor_principal"]

    principal_pago = conn.execute(
        """
        SELECT COALESCE(SUM(valor_principal), 0) AS total
        FROM parcelas_emprestimo
        WHERE emprestimo_id = ? AND status = ?
        """,
        (emprestimo_id, STATUS_PARCELA_PAGO),
    ).fetchone()["total"]

    return round(principal_original - principal_pago, 2)


def listar_emprestimos_ativos() -> List[Dict[str, Any]]:
    """
    Lista os empréstimos ativos, já com o nome do cliente e o saldo
    devedor de principal calculado.
    """

    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT e.*, c.nome AS nome_cliente
            FROM emprestimos e
            JOIN clientes_emprestimo c ON c.id = e.cliente_id
            WHERE e.status = ?
            ORDER BY c.nome
            """,
            (STATUS_EMPRESTIMO_ATIVO,),
        ).fetchall()

        resultado = []
        for linha in linhas:
            emprestimo = dict(linha)
            emprestimo["saldo_devedor"] = _saldo_devedor_emprestimo(conn, emprestimo["id"])
            resultado.append(emprestimo)

        return resultado


def listar_emprestimos_cliente(cliente_id: int) -> List[Dict[str, Any]]:
    """
    Lista todos os empréstimos (ativos e quitados) de um cliente.
    """

    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT * FROM emprestimos
            WHERE cliente_id = ?
            ORDER BY data_inicio DESC
            """,
            (cliente_id,),
        ).fetchall()

        resultado = []
        for linha in linhas:
            emprestimo = dict(linha)
            emprestimo["saldo_devedor"] = _saldo_devedor_emprestimo(conn, emprestimo["id"])
            resultado.append(emprestimo)

        return resultado


def listar_parcelas_emprestimo(emprestimo_id: int) -> List[Dict[str, Any]]:
    """
    Lista as parcelas de um empréstimo específico, em ordem cronológica.
    """

    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM parcelas_emprestimo
            WHERE emprestimo_id = ?
            ORDER BY numero
            """,
            (emprestimo_id,),
        )

        return [dict(linha) for linha in cursor.fetchall()]


def marcar_parcelas_atrasadas() -> None:
    """
    Atualiza para 'atrasado' toda parcela pendente cujo vencimento já
    passou. Deve ser chamada sempre que a tela de Empréstimos é aberta
    ou atualizada.
    """

    hoje = datetime.now().strftime("%Y-%m-%d")

    with conectar() as conn:
        conn.execute(
            """
            UPDATE parcelas_emprestimo
            SET status = ?
            WHERE status = ? AND data_vencimento < ?
            """,
            (STATUS_PARCELA_ATRASADO, STATUS_PARCELA_PENDENTE, hoje),
        )


def registrar_pagamento_parcela(
    parcela_id: int,
    valor_principal_pago: Optional[float] = None,
) -> None:
    """
    Marca uma parcela como paga. Se `valor_principal_pago` for informado,
    substitui o valor de principal planejado (útil quando o cliente paga
    um valor diferente do combinado). Se o saldo devedor do empréstimo
    zerar, o empréstimo é marcado como 'quitado'.
    """

    hoje = datetime.now().strftime("%Y-%m-%d")

    with conectar() as conn:
        parcela = conn.execute(
            "SELECT * FROM parcelas_emprestimo WHERE id = ?",
            (parcela_id,),
        ).fetchone()

        if parcela is None:
            raise ValueError("Parcela não encontrada.")

        principal_final = (
            parcela["valor_principal"] if valor_principal_pago is None else valor_principal_pago
        )

        conn.execute(
            """
            UPDATE parcelas_emprestimo
            SET status = ?, data_pagamento = ?, valor_principal = ?
            WHERE id = ?
            """,
            (STATUS_PARCELA_PAGO, hoje, principal_final, parcela_id),
        )

        saldo_devedor = _saldo_devedor_emprestimo(conn, parcela["emprestimo_id"])

        if saldo_devedor <= 0:
            conn.execute(
                "UPDATE emprestimos SET status = ? WHERE id = ?",
                (STATUS_EMPRESTIMO_QUITADO, parcela["emprestimo_id"]),
            )


def gerar_proxima_parcela(
    emprestimo_id: int,
    valor_principal_planejado: float = 0.0,
) -> int:
    """
    Gera a próxima cobrança de um empréstimo ativo, 30 dias após o
    vencimento da última parcela. `valor_principal_planejado = 0`
    representa uma prorrogação (mês em que o cliente paga somente juros).

    O juro continua sendo calculado sobre o valor_principal ORIGINAL do
    empréstimo, nunca sobre o saldo devedor.
    """

    with conectar() as conn:
        emprestimo = conn.execute(
            "SELECT * FROM emprestimos WHERE id = ?",
            (emprestimo_id,),
        ).fetchone()

        if emprestimo is None:
            raise ValueError("Empréstimo não encontrado.")

        if emprestimo["status"] != STATUS_EMPRESTIMO_ATIVO:
            raise ValueError("Este empréstimo já está quitado.")

        ultima_parcela = conn.execute(
            """
            SELECT * FROM parcelas_emprestimo
            WHERE emprestimo_id = ?
            ORDER BY numero DESC
            LIMIT 1
            """,
            (emprestimo_id,),
        ).fetchone()

        if ultima_parcela is not None and ultima_parcela["status"] != STATUS_PARCELA_PAGO:
            raise ValueError("Já existe uma parcela em aberto para este empréstimo.")

        saldo_devedor = _saldo_devedor_emprestimo(conn, emprestimo_id)
        principal_parcela = min(valor_principal_planejado or 0.0, saldo_devedor)

        proximo_numero = (ultima_parcela["numero"] + 1) if ultima_parcela else 1
        data_base = (
            datetime.strptime(ultima_parcela["data_vencimento"], "%Y-%m-%d")
            if ultima_parcela
            else datetime.strptime(emprestimo["data_inicio"], "%Y-%m-%d")
        )
        data_vencimento = (data_base + timedelta(days=30)).strftime("%Y-%m-%d")

        valor_juros_fixo = emprestimo["valor_principal"] * emprestimo["taxa_juros_mensal"]

        cursor = conn.execute(
            """
            INSERT INTO parcelas_emprestimo
            (emprestimo_id, numero, valor_juros, valor_principal, data_vencimento, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                emprestimo_id,
                proximo_numero,
                valor_juros_fixo,
                principal_parcela,
                data_vencimento,
                STATUS_PARCELA_PENDENTE,
            ),
        )

        return cursor.lastrowid


def calcular_resumo_emprestimos() -> Dict[str, float]:
    """
    Calcula os totais usados nos cards superiores da sub-aba Empréstimos:

        - capital_emprestado: soma do saldo devedor de todos os
          empréstimos ativos.
        - juros_recebidos: soma de todo juro já efetivamente recebido
          (histórico completo, inclusive de empréstimos quitados).
        - a_receber: soma (juros + principal) das parcelas pendentes.
        - em_atraso: soma (juros + principal) das parcelas atrasadas.
    """

    with conectar() as conn:
        emprestimos_ativos = conn.execute(
            "SELECT id FROM emprestimos WHERE status = ?",
            (STATUS_EMPRESTIMO_ATIVO,),
        ).fetchall()

        capital_emprestado = sum(
            _saldo_devedor_emprestimo(conn, linha["id"]) for linha in emprestimos_ativos
        )

        juros_recebidos = conn.execute(
            """
            SELECT COALESCE(SUM(valor_juros), 0) AS total
            FROM parcelas_emprestimo
            WHERE status = ?
            """,
            (STATUS_PARCELA_PAGO,),
        ).fetchone()["total"]

        a_receber = conn.execute(
            """
            SELECT COALESCE(SUM(valor_juros + valor_principal), 0) AS total
            FROM parcelas_emprestimo
            WHERE status = ?
            """,
            (STATUS_PARCELA_PENDENTE,),
        ).fetchone()["total"]

        em_atraso = conn.execute(
            """
            SELECT COALESCE(SUM(valor_juros + valor_principal), 0) AS total
            FROM parcelas_emprestimo
            WHERE status = ?
            """,
            (STATUS_PARCELA_ATRASADO,),
        ).fetchone()["total"]

        return {
            "capital_emprestado": round(capital_emprestado, 2),
            "juros_recebidos": round(juros_recebidos, 2),
            "a_receber": round(a_receber, 2),
            "em_atraso": round(em_atraso, 2),
        }


def calcular_margem_seguranca(cliente_id: int) -> Dict[str, float]:
    """
    Calcula a margem de segurança de um cliente:

        margem = juros já recebidos (todos os empréstimos do cliente)
                 - saldo devedor de principal (empréstimos ainda ativos)

    Uma margem positiva é o quanto dá para emprestar a mais a esse
    cliente sem risco de prejuízo, mesmo que ele não pague mais nada.
    """

    with conectar() as conn:
        juros_recebidos = conn.execute(
            """
            SELECT COALESCE(SUM(p.valor_juros), 0) AS total
            FROM parcelas_emprestimo p
            JOIN emprestimos e ON e.id = p.emprestimo_id
            WHERE e.cliente_id = ? AND p.status = ?
            """,
            (cliente_id, STATUS_PARCELA_PAGO),
        ).fetchone()["total"]

        emprestimos_ativos = conn.execute(
            "SELECT id FROM emprestimos WHERE cliente_id = ? AND status = ?",
            (cliente_id, STATUS_EMPRESTIMO_ATIVO),
        ).fetchall()

        saldo_devedor = sum(
            _saldo_devedor_emprestimo(conn, linha["id"]) for linha in emprestimos_ativos
        )

        return {
            "juros_recebidos": round(juros_recebidos, 2),
            "saldo_devedor": round(saldo_devedor, 2),
            "margem_seguranca": round(juros_recebidos - saldo_devedor, 2),
        }


def deletar_emprestimo(emprestimo_id: int) -> None:
    """
    Remove um empréstimo e todas as suas parcelas (uso administrativo,
    ex: cadastro feito por engano).
    """

    with conectar() as conn:
        conn.execute(
            "DELETE FROM parcelas_emprestimo WHERE emprestimo_id = ?",
            (emprestimo_id,),
        )
        conn.execute(
            "DELETE FROM emprestimos WHERE id = ?",
            (emprestimo_id,),
        )


# Permite testar o módulo isoladamente: `python database.py`
# ---------------------------------------------------------------------------
# MÓDULO VEÍCULOS
# ---------------------------------------------------------------------------

TIPO_VEICULO_CARRO = "Carro"
TIPO_VEICULO_MOTO = "Moto"

CRITICIDADE_ALTA = "Alta"
CRITICIDADE_MEDIA = "Média"
CRITICIDADE_BAIXA = "Baixa"

STATUS_MANUTENCAO_EM_DIA = "Em dia"
STATUS_MANUTENCAO_ATENCAO = "Atenção"
STATUS_MANUTENCAO_VENCIDO = "Vencido"

# Limiares para status "Atenção" (perto do vencimento, mas ainda não vencido).
LIMIAR_ATENCAO_KM = 500
LIMIAR_ATENCAO_DIAS = 30

# Itens típicos pré-cadastrados ao criar um veículo, calibrados a partir dos
# manuais oficiais (Honda City / CBR600F) e de prática geral para carros mais
# antigos (ex: Gol 1.0 2002). O usuário pode editar, excluir ou adicionar
# itens livremente depois — isso é só um ponto de partida.
# Formato de cada item: (nome, intervalo_km, intervalo_dias, criticidade)
SEEDS_ITENS_MANUTENCAO = {
    TIPO_VEICULO_CARRO: [
        ("Troca de óleo e filtro de óleo", 5000, 180, CRITICIDADE_ALTA),
        ("Filtro de ar do motor", 10000, 365, CRITICIDADE_MEDIA),
        ("Filtro de cabine (ar-condicionado)", 10000, 365, CRITICIDADE_BAIXA),
        ("Pastilhas e discos de freio (verificação)", 10000, None, CRITICIDADE_ALTA),
        ("Velas de ignição", 20000, 730, CRITICIDADE_MEDIA),
        ("Fluido de freio", None, 730, CRITICIDADE_ALTA),
        ("Líquido de arrefecimento", None, 730, CRITICIDADE_MEDIA),
        ("Correia dentada / corrente de comando (verificar no manual)", 60000, 1825, CRITICIDADE_ALTA),
        ("Calibragem e rodízio de pneus", 10000, None, CRITICIDADE_BAIXA),
        ("Seguro (renovação)", None, 365, CRITICIDADE_ALTA),
        ("Licenciamento/CRLV (renovação)", None, 365, CRITICIDADE_ALTA),
    ],
    TIPO_VEICULO_MOTO: [
        ("Troca de óleo e filtro de óleo", 6000, 365, CRITICIDADE_ALTA),
        ("Verificar, ajustar e lubrificar a corrente de transmissão", 1000, None, CRITICIDADE_ALTA),
        ("Vela de ignição", 12000, 365, CRITICIDADE_MEDIA),
        ("Folga das válvulas", 12000, None, CRITICIDADE_MEDIA),
        ("Fluido de freio", None, 730, CRITICIDADE_ALTA),
        ("Pastilhas de freio (verificação)", 6000, None, CRITICIDADE_ALTA),
        ("Filtro de ar", 12000, None, CRITICIDADE_MEDIA),
        ("Pneus (desgaste/calibragem)", 3000, None, CRITICIDADE_BAIXA),
        ("Seguro (renovação)", None, 365, CRITICIDADE_ALTA),
        ("Licenciamento/CRLV (renovação)", None, 365, CRITICIDADE_ALTA),
    ],
}


def criar_veiculo(
    apelido: str,
    tipo: str,
    marca: str = "",
    modelo: str = "",
    ano: Optional[int] = None,
    km_atual: int = 0,
) -> int:
    """
    Cadastra um veículo e já pré-popula seu plano de manutenção com os itens
    típicos do tipo (Carro/Moto), conforme SEEDS_ITENS_MANUTENCAO.
    """

    apelido = (apelido or "").strip()
    if not apelido:
        raise ValueError("Informe um apelido para o veículo.")

    if tipo not in (TIPO_VEICULO_CARRO, TIPO_VEICULO_MOTO):
        raise ValueError("Tipo de veículo inválido.")

    if km_atual < 0:
        raise ValueError("A quilometragem não pode ser negativa.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO veiculos (apelido, tipo, marca, modelo, ano, km_atual)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (apelido, tipo, (marca or "").strip(), (modelo or "").strip(), ano, km_atual),
        )
        veiculo_id = cursor.lastrowid

        for nome_item, intervalo_km, intervalo_dias, criticidade in SEEDS_ITENS_MANUTENCAO.get(tipo, []):
            conn.execute(
                """
                INSERT INTO itens_manutencao_veiculo
                (veiculo_id, nome_item, intervalo_km, intervalo_dias, km_ultima_troca, data_ultima_troca, criticidade)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (veiculo_id, nome_item, intervalo_km, intervalo_dias, km_atual, None, criticidade),
            )

        return veiculo_id


def listar_veiculos() -> List[Dict[str, Any]]:
    """Lista todos os veículos cadastrados."""
    with conectar() as conn:
        cursor = conn.execute("SELECT * FROM veiculos ORDER BY apelido")
        return [dict(linha) for linha in cursor.fetchall()]


def obter_veiculo(veiculo_id: int) -> Optional[Dict[str, Any]]:
    """Retorna os dados de um veículo específico, ou None se não existir."""
    with conectar() as conn:
        linha = conn.execute("SELECT * FROM veiculos WHERE id = ?", (veiculo_id,)).fetchone()
        return dict(linha) if linha else None


def atualizar_km_veiculo(veiculo_id: int, novo_km: int) -> None:
    """
    Atualiza a quilometragem atual do veículo. O odômetro não pode
    retroceder — só aceita valores maiores ou iguais ao km atual salvo.
    """

    with conectar() as conn:
        atual = conn.execute(
            "SELECT km_atual FROM veiculos WHERE id = ?", (veiculo_id,),
        ).fetchone()

        if atual is None:
            raise ValueError("Veículo não encontrado.")

        if novo_km < atual["km_atual"]:
            raise ValueError(
                f"O novo km ({novo_km}) não pode ser menor que o km atual salvo ({atual['km_atual']})."
            )

        conn.execute("UPDATE veiculos SET km_atual = ? WHERE id = ?", (novo_km, veiculo_id))


def deletar_veiculo(veiculo_id: int) -> None:
    """Remove um veículo e tudo vinculado a ele (itens, histórico, abastecimentos)."""
    with conectar() as conn:
        if conn.execute("SELECT id FROM veiculos WHERE id = ?", (veiculo_id,)).fetchone() is None:
            raise ValueError("Veículo não encontrado.")
        conn.execute("DELETE FROM veiculos WHERE id = ?", (veiculo_id,))


def adicionar_item_manutencao(
    veiculo_id: int,
    nome_item: str,
    intervalo_km: Optional[int] = None,
    intervalo_dias: Optional[int] = None,
    criticidade: str = CRITICIDADE_MEDIA,
) -> int:
    """Adiciona um item ao plano de manutenção de um veículo."""

    nome_item = (nome_item or "").strip()
    if not nome_item:
        raise ValueError("Informe o nome do item de manutenção.")

    if intervalo_km is None and intervalo_dias is None:
        raise ValueError("Informe um intervalo por km e/ou por tempo.")

    with conectar() as conn:
        veiculo = conn.execute(
            "SELECT km_atual FROM veiculos WHERE id = ?", (veiculo_id,),
        ).fetchone()
        if veiculo is None:
            raise ValueError("Veículo não encontrado.")

        cursor = conn.execute(
            """
            INSERT INTO itens_manutencao_veiculo
            (veiculo_id, nome_item, intervalo_km, intervalo_dias, km_ultima_troca, data_ultima_troca, criticidade)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (veiculo_id, nome_item, intervalo_km, intervalo_dias, veiculo["km_atual"], None, criticidade),
        )
        return cursor.lastrowid


def deletar_item_manutencao(item_id: int) -> None:
    """Remove um item do plano de manutenção (não apaga o histórico já registrado)."""
    with conectar() as conn:
        conn.execute("DELETE FROM itens_manutencao_veiculo WHERE id = ?", (item_id,))


def _calcular_status_item(
    item: Dict[str, Any], km_atual: int,
) -> Dict[str, Any]:
    """Calcula km/dias restantes e o status de um item de manutenção."""

    km_restante = None
    dias_restantes = None

    if item["intervalo_km"] is not None:
        base_km = item["km_ultima_troca"] if item["km_ultima_troca"] is not None else km_atual
        km_restante = (base_km + item["intervalo_km"]) - km_atual

    if item["intervalo_dias"] is not None and item["data_ultima_troca"]:
        proxima_data = (
            datetime.strptime(item["data_ultima_troca"], "%Y-%m-%d")
            + timedelta(days=item["intervalo_dias"])
        ).date()
        dias_restantes = (proxima_data - datetime.now().date()).days

    def _status_de(valor: Optional[float], limiar: float) -> Optional[str]:
        if valor is None:
            return None
        if valor <= 0:
            return STATUS_MANUTENCAO_VENCIDO
        if valor <= limiar:
            return STATUS_MANUTENCAO_ATENCAO
        return STATUS_MANUTENCAO_EM_DIA

    status_km = _status_de(km_restante, LIMIAR_ATENCAO_KM)
    status_dias = _status_de(dias_restantes, LIMIAR_ATENCAO_DIAS)

    ordem = {STATUS_MANUTENCAO_VENCIDO: 0, STATUS_MANUTENCAO_ATENCAO: 1, STATUS_MANUTENCAO_EM_DIA: 2}
    status_candidatos = [s for s in (status_km, status_dias) if s is not None]
    status_final = min(status_candidatos, key=lambda s: ordem[s]) if status_candidatos else STATUS_MANUTENCAO_EM_DIA

    resultado = dict(item)
    resultado["km_restante"] = km_restante
    resultado["dias_restantes"] = dias_restantes
    resultado["status"] = status_final
    return resultado


def listar_itens_manutencao(veiculo_id: int) -> List[Dict[str, Any]]:
    """
    Lista os itens do plano de manutenção de um veículo, cada um já com
    km/dias restantes e status ('Em dia' / 'Atenção' / 'Vencido')
    calculados. Ordenado do mais urgente para o menos urgente.
    """

    with conectar() as conn:
        veiculo = conn.execute(
            "SELECT km_atual FROM veiculos WHERE id = ?", (veiculo_id,),
        ).fetchone()
        if veiculo is None:
            return []

        itens = conn.execute(
            "SELECT * FROM itens_manutencao_veiculo WHERE veiculo_id = ? ORDER BY nome_item",
            (veiculo_id,),
        ).fetchall()

        resultado = [_calcular_status_item(dict(item), veiculo["km_atual"]) for item in itens]

        ordem = {STATUS_MANUTENCAO_VENCIDO: 0, STATUS_MANUTENCAO_ATENCAO: 1, STATUS_MANUTENCAO_EM_DIA: 2}
        resultado.sort(key=lambda i: ordem[i["status"]])
        return resultado


def registrar_manutencao_realizada(
    veiculo_id: int,
    descricao: str,
    data: str,
    km: Optional[int] = None,
    custo: Optional[float] = None,
    local: str = "",
    item_id: Optional[int] = None,
) -> int:
    """
    Registra uma manutenção como realizada (histórico). Se `item_id` for
    informado, também atualiza o km/data da última troca desse item, o que
    recalcula automaticamente a próxima data de vencimento.
    """

    descricao = (descricao or "").strip()
    if not descricao:
        raise ValueError("Informe a descrição da manutenção.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO manutencoes_realizadas (veiculo_id, item_id, descricao, data, km, custo, local)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (veiculo_id, item_id, descricao, data, km, custo, (local or "").strip()),
        )

        if item_id is not None:
            conn.execute(
                "UPDATE itens_manutencao_veiculo SET km_ultima_troca = ?, data_ultima_troca = ? WHERE id = ?",
                (km, data, item_id),
            )

        if km is not None:
            veiculo = conn.execute(
                "SELECT km_atual FROM veiculos WHERE id = ?", (veiculo_id,),
            ).fetchone()
            if veiculo is not None and km > veiculo["km_atual"]:
                conn.execute("UPDATE veiculos SET km_atual = ? WHERE id = ?", (km, veiculo_id))

        return cursor.lastrowid


def listar_manutencoes_realizadas(veiculo_id: int) -> List[Dict[str, Any]]:
    """Histórico de manutenções realizadas de um veículo, mais recente primeiro."""
    with conectar() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM manutencoes_realizadas
            WHERE veiculo_id = ?
            ORDER BY data DESC, id DESC
            """,
            (veiculo_id,),
        )
        return [dict(linha) for linha in cursor.fetchall()]


def adicionar_abastecimento(
    veiculo_id: int,
    data: str,
    km: int,
    litros: float,
    valor_total: float,
    combustivel: str,
) -> int:
    """Registra um abastecimento e atualiza o km atual do veículo se for maior."""

    if litros <= 0:
        raise ValueError("A quantidade de litros deve ser maior que zero.")
    if valor_total <= 0:
        raise ValueError("O valor do abastecimento deve ser maior que zero.")

    with conectar() as conn:
        cursor = conn.execute(
            """
            INSERT INTO abastecimentos (veiculo_id, data, km, litros, valor_total, combustivel)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (veiculo_id, data, km, litros, valor_total, combustivel),
        )

        veiculo = conn.execute(
            "SELECT km_atual FROM veiculos WHERE id = ?", (veiculo_id,),
        ).fetchone()
        if veiculo is not None and km > veiculo["km_atual"]:
            conn.execute("UPDATE veiculos SET km_atual = ? WHERE id = ?", (km, veiculo_id))

        return cursor.lastrowid


def listar_abastecimentos_com_consumo(veiculo_id: int) -> List[Dict[str, Any]]:
    """
    Lista os abastecimentos de um veículo (mais recente primeiro), cada um
    já com o consumo (km/L) calculado em relação ao abastecimento anterior
    — pressupõe tanque cheio a cada abastecimento, que é o método padrão.
    """

    with conectar() as conn:
        cursor = conn.execute(
            "SELECT * FROM abastecimentos WHERE veiculo_id = ? ORDER BY data, km",
            (veiculo_id,),
        )
        abastecimentos = [dict(linha) for linha in cursor.fetchall()]

    resultado = []
    for i, abastecimento in enumerate(abastecimentos):
        consumo_km_l = None
        if i > 0:
            km_percorrido = abastecimento["km"] - abastecimentos[i - 1]["km"]
            if km_percorrido > 0 and abastecimento["litros"] > 0:
                consumo_km_l = round(km_percorrido / abastecimento["litros"], 2)
        abastecimento["consumo_km_l"] = consumo_km_l
        resultado.append(abastecimento)

    resultado.reverse()
    return resultado


def calcular_resumo_veiculo(veiculo_id: int) -> Dict[str, Any]:
    """
    Calcula os números usados nos cards de resumo de um veículo: gasto total
    em manutenção, gasto total em combustível, consumo médio (km/L) e
    quantos itens do plano estão vencidos/em atenção.
    """

    with conectar() as conn:
        gasto_manutencao = conn.execute(
            "SELECT COALESCE(SUM(custo), 0) AS total FROM manutencoes_realizadas WHERE veiculo_id = ?",
            (veiculo_id,),
        ).fetchone()["total"]

        gasto_combustivel = conn.execute(
            "SELECT COALESCE(SUM(valor_total), 0) AS total FROM abastecimentos WHERE veiculo_id = ?",
            (veiculo_id,),
        ).fetchone()["total"]

    abastecimentos = listar_abastecimentos_com_consumo(veiculo_id)
    consumos_validos = [a["consumo_km_l"] for a in abastecimentos if a["consumo_km_l"] is not None]
    consumo_medio = round(sum(consumos_validos) / len(consumos_validos), 2) if consumos_validos else None

    itens = listar_itens_manutencao(veiculo_id)
    qtd_vencidos = sum(1 for i in itens if i["status"] == STATUS_MANUTENCAO_VENCIDO)
    qtd_atencao = sum(1 for i in itens if i["status"] == STATUS_MANUTENCAO_ATENCAO)

    return {
        "gasto_manutencao": round(gasto_manutencao, 2),
        "gasto_combustivel": round(gasto_combustivel, 2),
        "consumo_medio_km_l": consumo_medio,
        "qtd_vencidos": qtd_vencidos,
        "qtd_atencao": qtd_atencao,
    }


if __name__ == "__main__":
    inicializar_banco()
    print("Tabelas criadas/verificadas com sucesso.")