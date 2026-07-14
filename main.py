"""
main.py
--------
Ponto de entrada do GMBTech Dashboard.

Responsável por:
    - Inicializar o banco de dados (database.py).
    - Montar a interface gráfica em Flet (tema escuro).
    - Navegação por seções: Dashboard, Estudos & Editais, Configurações.
    - Fluxo de importação de editais via JSON (FilePicker).
    - Exibição em árvore (Matérias -> Tópicos) com checkbox de status.
    - Persistência da API Key do Google AI Studio.

Para executar:
    pip install flet
    python main.py

Estrutura de pastas esperada (a partir da raiz do projeto, onde este arquivo fica):
    main.py
    src/
        database/
            database.py
        services/
            ai_service.py

Se você reorganizar as pastas novamente, ajuste apenas a lista `CAMINHOS_MODULOS`
abaixo — o resto do arquivo não precisa mudar.
"""

import os
import sys
import threading
from datetime import datetime, timedelta
from typing import Optional

import flet as ft

# ---------------------------------------------------------------------------
# LOCALIZAÇÃO DOS MÓDULOS (database.py e ai_service.py)
# ---------------------------------------------------------------------------
# Como o projeto está organizado em subpastas (src/database, src/services),
# adicionamos essas pastas ao sys.path antes de importar, para que
# `import database` e `import ai_service` funcionem independentemente de
# onde o main.py seja executado.
_DIR_BASE = os.path.dirname(os.path.abspath(__file__))
CAMINHOS_MODULOS = [
    os.path.join(_DIR_BASE, "src", "database"),
    os.path.join(_DIR_BASE, "src", "services"),
]
for _caminho in CAMINHOS_MODULOS:
    if os.path.isdir(_caminho) and _caminho not in sys.path:
        sys.path.insert(0, _caminho)

import database as db
import ai_service
import calendar_service


# ---------------------------------------------------------------------------
# CONSTANTES
# ---------------------------------------------------------------------------

CHAVE_API_GOOGLE_AI = "google_ai_studio_api_key"
CHAVE_GOOGLE_CALENDAR_ID = "google_calendar_id"

STATUS_NAO_INICIADO = "Não Iniciado"
STATUS_VISTO = "Visto"


def main(page: ft.Page) -> None:
    # -----------------------------------------------------------------
    # CONFIGURAÇÃO GERAL DA PÁGINA
    # -----------------------------------------------------------------
    page.title = "GMBTech Dashboard"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.width = 1100
    page.window.height = 750
    page.window.min_width = 900
    page.window.min_height = 600
    page.padding = 0
    page.bgcolor = ft.Colors.BLACK

    # Inicializa o banco de dados (cria tabelas se não existirem).
    db.inicializar_banco()

    # Estado em memória da sessão atual.
    estado = {"edital_id_ativo": None}

    # -----------------------------------------------------------------
    # COMPONENTES COMPARTILHADOS / FEEDBACK
    # -----------------------------------------------------------------

    snack = ft.SnackBar(content=ft.Text(""))
    # NOTA: NÃO adicionamos ao page.overlay aqui ainda. O SnackBar (controle
    # visual) só deve ser registrado no overlay DEPOIS que o primeiro page.update()/page.add() completar o handshake inicial com o
    # cliente Flet — do contrário, o cliente pode não reconhecer o controle
    # e exibir o erro "Unknown control" (bug conhecido em versões recentes
    # do Flet quando Service controls são adicionados antes do 1º render).

    def notificar(mensagem: str, erro: bool = False) -> None:
        """Exibe uma notificação rápida (SnackBar) na parte inferior da tela."""
        snack.content = ft.Text(mensagem)
        snack.bgcolor = ft.Colors.RED_700 if erro else ft.Colors.GREEN_700
        snack.open = True
        page.update()

    # ===================================================================
    # ABA: CONFIGURAÇÕES
    # ===================================================================

    campo_api_key = ft.TextField(
        label="Google AI Studio API Key",
        password=True,
        can_reveal_password=True,
        width=420,
        value=db.obter_configuracao(CHAVE_API_GOOGLE_AI, "") or "",
        border_color=ft.Colors.BLUE_400,
    )

    def salvar_api_key(e: ft.ControlEvent) -> None:
        valor = campo_api_key.value.strip()
        if not valor:
            notificar("Informe uma API Key válida antes de salvar.", erro=True)
            return
        db.salvar_configuracao(CHAVE_API_GOOGLE_AI, valor)
        notificar("API Key salva com sucesso!")

    # --- Seção: Sincronização com Google Agenda (setup inicial p/ Fase 4) --

    campo_calendar_id = ft.TextField(
        label="Google Calendar ID (Agenda Principal)",
        width=420,
        value=db.obter_configuracao(CHAVE_GOOGLE_CALENDAR_ID, "") or "",
        border_color=ft.Colors.BLUE_400,
        hint_text="ex: seuemail@gmail.com ou um ID de agenda secundária",
    )

    def salvar_calendar_id(e: ft.ControlEvent) -> None:
        valor = campo_calendar_id.value.strip()
        if not valor:
            notificar("Informe um Calendar ID válido antes de salvar.", erro=True)
            return
        db.salvar_configuracao(CHAVE_GOOGLE_CALENDAR_ID, valor)
        notificar("Calendar ID salvo com sucesso!")

    progress_ring_calendar = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)

    def validar_conexao_calendar(e: ft.ControlEvent) -> None:
        """
        Executa a autenticação OAuth2 real com o Google (calendar_service.py)
        em uma thread separada — no primeiro login isso abre o navegador do
        usuário e pode demorar, então a UI não pode travar esperando.
        """
        if not campo_calendar_id.value or not campo_calendar_id.value.strip():
            notificar("Informe um Calendar ID antes de validar.", erro=True)
            return

        botao_validar_calendar.disabled = True
        progress_ring_calendar.visible = True
        page.update()

        def tarefa_em_background() -> None:
            try:
                calendar_service.obter_credenciais_google()
                notificar("Conexão com a Google Agenda validada com sucesso!")
            except calendar_service.CredentialsArquivoNaoEncontradoError:
                notificar(
                    "Arquivo credentials.json não encontrado na raiz do projeto.",
                    erro=True,
                )
            except calendar_service.ErroAutenticacaoGoogleError as ea:
                notificar(str(ea), erro=True)
            except Exception as ex:
                notificar(f"Erro inesperado ao validar a conexão: {ex}", erro=True)
            finally:
                botao_validar_calendar.disabled = False
                progress_ring_calendar.visible = False
                page.update()

        threading.Thread(target=tarefa_em_background, daemon=True).start()

    botao_validar_calendar = ft.Button(
        "Validar Conexão com Agenda",
        icon=ft.Icons.EVENT_AVAILABLE,
        on_click=validar_conexao_calendar,
        bgcolor=ft.Colors.TEAL_700,
        color=ft.Colors.WHITE,
    )

    aba_configuracoes = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=20,
            controls=[
                ft.Text("Configurações", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Text(
                    "Integrações",
                    size=16,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.GREY_400,
                ),
                campo_api_key,
                ft.Button(
                    "Salvar",
                    icon=ft.Icons.SAVE,
                    on_click=salvar_api_key,
                    bgcolor=ft.Colors.BLUE_600,
                    color=ft.Colors.WHITE,
                ),
                ft.Divider(),
                ft.Text(
                    "Sincronização com Google Agenda",
                    size=16,
                    weight=ft.FontWeight.W_600,
                    color=ft.Colors.GREY_400,
                ),
                campo_calendar_id,
                ft.Row(
                    spacing=12,
                    controls=[
                        ft.Button(
                            "Salvar",
                            icon=ft.Icons.SAVE,
                            on_click=salvar_calendar_id,
                            bgcolor=ft.Colors.BLUE_600,
                            color=ft.Colors.WHITE,
                        ),
                        botao_validar_calendar,
                        progress_ring_calendar,
                    ],
                ),
            ],
        ),
    )

    # ===================================================================
    # ABA: ESTUDOS & EDITAIS
    # ===================================================================

    lista_topicos = ft.ListView(expand=True, spacing=4, padding=10, auto_scroll=False)

    dropdown_editais = ft.Dropdown(
        label="Edital ativo",
        width=400,
        options=[],
        on_select=lambda e: selecionar_edital(e.control.value),
    )

    def carregar_editais_no_dropdown(selecionar_id: int = None) -> None:
        """Recarrega a lista de editais do banco e popula o Dropdown."""
        editais = db.listar_editais()
        dropdown_editais.options = [
            ft.dropdown.Option(key=str(ed["id"]), text=ed["nome"]) for ed in editais
        ]

        if selecionar_id is not None:
            dropdown_editais.value = str(selecionar_id)
            selecionar_edital(str(selecionar_id))
        elif editais:
            dropdown_editais.value = str(editais[0]["id"])
            selecionar_edital(str(editais[0]["id"]))
        else:
            estado["edital_id_ativo"] = None
            dropdown_editais.value = None
            lista_topicos.controls.clear()
            atualizar_indicador_pdf()
            atualizar_painel_estudos_extra()

        page.update()

    def alternar_status_topico(topico_id: int, checked: bool) -> None:
        """Callback do checkbox: atualiza o status do tópico no banco."""
        novo_status = STATUS_VISTO if checked else STATUS_NAO_INICIADO
        db.atualizar_status_topico(topico_id, novo_status)
        notificar(f"Tópico marcado como '{novo_status}'.")

    # --- Exclusão do edital ativo (ação destrutiva, exige confirmação) -------

    texto_confirmacao_exclusao_edital = ft.Text("")

    def fechar_dialogo_confirmar_exclusao_edital(e: ft.ControlEvent = None) -> None:
        dialogo_confirmar_exclusao_edital.open = False
        page.update()

    def abrir_dialogo_confirmar_exclusao_edital(e: ft.ControlEvent = None) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return
        edital = db.obter_edital_por_id(edital_id)
        nome = edital["nome"] if edital else "este edital"
        texto_confirmacao_exclusao_edital.value = (
            f'Tem certeza que deseja excluir "{nome}"? Isso apaga TODAS as matérias, '
            "tópicos, questões registradas, cronograma e metas desse edital. "
            "Essa ação não pode ser desfeita."
        )
        dialogo_confirmar_exclusao_edital.open = True
        page.update()

    def confirmar_exclusao_edital(e: ft.ControlEvent) -> None:
        edital_id = estado["edital_id_ativo"]
        try:
            db.deletar_edital(edital_id)
        except ValueError as ve:
            notificar(str(ve), erro=True)
            fechar_dialogo_confirmar_exclusao_edital()
            return

        fechar_dialogo_confirmar_exclusao_edital()
        notificar("Edital excluído.")
        carregar_editais_no_dropdown()

    botao_excluir_edital = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE,
        icon_color=ft.Colors.RED_300,
        tooltip="Excluir edital ativo",
        on_click=abrir_dialogo_confirmar_exclusao_edital,
    )

    dialogo_confirmar_exclusao_edital = ft.AlertDialog(
        modal=True,
        title=ft.Text("Excluir Edital"),
        content=texto_confirmacao_exclusao_edital,
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_confirmar_exclusao_edital),
            ft.Button(
                "Excluir",
                icon=ft.Icons.DELETE_OUTLINE,
                bgcolor=ft.Colors.RED_700,
                color=ft.Colors.WHITE,
                on_click=confirmar_exclusao_edital,
            ),
        ],
    )

    # -----------------------------------------------------------------
    # DIÁLOGO: "Registrar Questões" (rendimento em simulados/treinos)
    # -----------------------------------------------------------------
    # Instanciado de forma isolada (uma única vez, reaproveitado por todos
    # os tópicos/matérias) e registrado no page.overlay somente depois do
    # primeiro render — mesmo cuidado já aplicado ao SnackBar, para evitar
    # o bug "Unknown control" em versões recentes do Flet.

    contexto_rendimento = {"edital_id": None, "materia_id": None, "topico_id": None}

    texto_titulo_dialogo = ft.Text("Registrar Questões", weight=ft.FontWeight.BOLD)

    campo_total_questoes = ft.TextField(
        label="Total de Questões Feitas",
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
        autofocus=True,
    )
    campo_acertos = ft.TextField(
        label="Quantidade de Acertos",
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )

    def fechar_dialogo_rendimento(e: ft.ControlEvent = None) -> None:
        dialogo_rendimento.open = False
        page.update()

    def abrir_dialogo_rendimento(materia_id: int, topico_id: Optional[int], rotulo: str) -> None:
        """Abre o diálogo de registro, guardando o contexto (matéria/tópico) atual."""
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return

        contexto_rendimento["edital_id"] = edital_id
        contexto_rendimento["materia_id"] = materia_id
        contexto_rendimento["topico_id"] = topico_id

        texto_titulo_dialogo.value = f"Registrar Questões — {rotulo}"
        campo_total_questoes.value = ""
        campo_acertos.value = ""
        dialogo_rendimento.open = True
        page.update()

    def salvar_rendimento(e: ft.ControlEvent) -> None:
        total_str = (campo_total_questoes.value or "").strip()
        acertos_str = (campo_acertos.value or "").strip()

        if not total_str or not acertos_str:
            notificar("Preencha o total de questões e os acertos.", erro=True)
            return

        try:
            total = int(total_str)
            acertos = int(acertos_str)
            db.registrar_desempenho_simulado(
                edital_id=contexto_rendimento["edital_id"],
                materia_id=contexto_rendimento["materia_id"],
                topico_id=contexto_rendimento["topico_id"],
                total=total,
                acertos=acertos,
            )
        except ValueError as ve:
            notificar(str(ve), erro=True)
            return
        except Exception as ex:
            notificar(f"Erro inesperado ao registrar rendimento: {ex}", erro=True)
            return

        fechar_dialogo_rendimento()
        notificar(f"Rendimento registrado: {acertos}/{total} acertos.")
        construir_arvore_edital(contexto_rendimento["edital_id"])
        atualizar_cards_dashboard()

    dialogo_rendimento = ft.AlertDialog(
        modal=True,
        title=texto_titulo_dialogo,
        content=ft.Column(
            tight=True,
            spacing=12,
            controls=[campo_total_questoes, campo_acertos],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_rendimento),
            ft.Button(
                "Salvar Rendimento",
                icon=ft.Icons.SAVE,
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
                on_click=salvar_rendimento,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    # -----------------------------------------------------------------
    # DIÁLOGO: "Agendar Bloco de Estudo" (Google Calendar - Fase 4)
    # -----------------------------------------------------------------
    # Mesmo padrão do diálogo de rendimento: instância única, isolada,
    # registrada no page.overlay só depois do primeiro render.

    DURACOES_MINUTOS = {"1h": 60, "1h30": 90, "2h": 120, "3h": 180}

    contexto_agendamento = {"titulo": None}

    texto_titulo_dialogo_agendamento = ft.Text("Agendar Bloco de Estudo", weight=ft.FontWeight.BOLD)

    campo_data_hora_agendamento = ft.TextField(
        label="Data e Horário Inicial",
        hint_text="DD/MM/AAAA HH:MM (ex: 10/07/2026 14:00)",
        autofocus=True,
    )
    dropdown_duracao_agendamento = ft.Dropdown(
        label="Duração",
        value="1h",
        options=[ft.dropdown.Option(key=k, text=k) for k in DURACOES_MINUTOS],
    )
    progress_ring_agendamento = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)

    def fechar_dialogo_agendamento(e: ft.ControlEvent = None) -> None:
        dialogo_agendamento.open = False
        page.update()

    def abrir_dialogo_agendamento(rotulo: str) -> None:
        """Abre o diálogo de agendamento, guardando o título do evento a ser criado."""
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return

        calendar_id = db.obter_configuracao(CHAVE_GOOGLE_CALENDAR_ID)
        if not calendar_id or not calendar_id.strip():
            notificar(
                "Configure o Calendar ID na aba Configurações antes de agendar.",
                erro=True,
            )
            return

        contexto_agendamento["titulo"] = f"Estudo: {rotulo}"
        texto_titulo_dialogo_agendamento.value = f"Agendar Bloco de Estudo — {rotulo}"
        campo_data_hora_agendamento.value = ""
        dropdown_duracao_agendamento.value = "1h"
        dialogo_agendamento.open = True
        page.update()

    def confirmar_agendamento(e: ft.ControlEvent) -> None:
        texto_data = (campo_data_hora_agendamento.value or "").strip()
        if not texto_data:
            notificar("Informe a data e o horário do bloco de estudo.", erro=True)
            return

        try:
            inicio = datetime.strptime(texto_data, "%d/%m/%Y %H:%M")
        except ValueError:
            notificar(
                "Data/horário inválido. Use exatamente o formato DD/MM/AAAA HH:MM.",
                erro=True,
            )
            return

        calendar_id = db.obter_configuracao(CHAVE_GOOGLE_CALENDAR_ID)
        if not calendar_id or not calendar_id.strip():
            notificar(
                "Configure o Calendar ID na aba Configurações antes de agendar.",
                erro=True,
            )
            return

        duracao_min = DURACOES_MINUTOS.get(dropdown_duracao_agendamento.value, 60)
        fim = inicio + timedelta(minutes=duracao_min)
        titulo_evento = contexto_agendamento["titulo"]

        # Estado de "carregando": a criação do evento envolve rede (e, no
        # primeiro uso, o login OAuth2 no navegador) — nunca trava a UI.
        botao_confirmar_agendamento.disabled = True
        progress_ring_agendamento.visible = True
        page.update()

        def tarefa_em_background() -> None:
            try:
                link = calendar_service.criar_bloco_estudo_agenda(
                    calendar_id=calendar_id.strip(),
                    titulo=titulo_evento,
                    data_inicio_iso=inicio.isoformat(),
                    data_fim_iso=fim.isoformat(),
                    descricao="Bloco de estudo agendado automaticamente pelo GMBTech Dashboard.",
                )
                fechar_dialogo_agendamento()
                notificar(f"Bloco de estudo agendado com sucesso! Link: {link}")

            except calendar_service.CredentialsArquivoNaoEncontradoError:
                notificar(
                    "Arquivo credentials.json não encontrado na raiz do projeto.",
                    erro=True,
                )
            except calendar_service.ErroAutenticacaoGoogleError as ea:
                notificar(str(ea), erro=True)
            except calendar_service.ErroAgendaGoogleError as eg:
                notificar(str(eg), erro=True)
            except Exception as ex:
                notificar(f"Erro inesperado ao agendar o bloco de estudo: {ex}", erro=True)
            finally:
                botao_confirmar_agendamento.disabled = False
                progress_ring_agendamento.visible = False
                page.update()

        threading.Thread(target=tarefa_em_background, daemon=True).start()

    botao_confirmar_agendamento = ft.Button(
        "Confirmar Agendamento na Agenda",
        icon=ft.Icons.EVENT_AVAILABLE,
        bgcolor=ft.Colors.GREEN_700,
        color=ft.Colors.WHITE,
        on_click=confirmar_agendamento,
    )

    dialogo_agendamento = ft.AlertDialog(
        modal=True,
        title=texto_titulo_dialogo_agendamento,
        content=ft.Column(
            tight=True,
            spacing=12,
            controls=[campo_data_hora_agendamento, dropdown_duracao_agendamento],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_agendamento),
            progress_ring_agendamento,
            botao_confirmar_agendamento,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def construir_arvore_edital(edital_id: int) -> None:
        """Monta a árvore visual de Matérias -> Tópicos para o edital selecionado."""
        lista_topicos.controls.clear()
        estrutura = db.obter_estrutura_edital(edital_id)

        if not estrutura:
            lista_topicos.controls.append(
                ft.Text("Nenhuma matéria encontrada para este edital.", italic=True)
            )
            page.update()
            return

        for materia in estrutura:
            linhas_topicos = []
            for topico in materia["topicos"]:
                marcado = topico["status"] != STATUS_NAO_INICIADO
                linhas_topicos.append(
                    ft.Row(
                        controls=[
                            ft.Checkbox(
                                value=marcado,
                                on_change=lambda e, tid=topico["id"]: alternar_status_topico(
                                    tid, e.control.value
                                ),
                            ),
                            ft.Text(topico["nome"], expand=True),
                            ft.Container(
                                content=ft.Text(
                                    f"Rendimento: {topico['rendimento_simulados']}%",
                                    size=11,
                                    color=ft.Colors.AMBER_300,
                                ),
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                bgcolor=ft.Colors.GREY_900,
                                border_radius=12,
                            ) if topico["rendimento_simulados"] else ft.Container(),
                            ft.IconButton(
                                icon=ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED,
                                icon_size=18,
                                tooltip="Registrar Questões deste tópico",
                                on_click=lambda e, mid=materia["id"], tid=topico["id"], nome=topico["nome"]: (
                                    abrir_dialogo_rendimento(mid, tid, nome)
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CALENDAR_TODAY,
                                icon_size=18,
                                tooltip="Agendar Bloco de Estudo",
                                on_click=lambda e, nome=topico["nome"]: (
                                    abrir_dialogo_agendamento(nome)
                                ),
                            ),
                            ft.Container(
                                content=ft.Text(
                                    topico["status"],
                                    size=11,
                                    color=ft.Colors.GREEN_300
                                    if marcado
                                    else ft.Colors.GREY_500,
                                ),
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                bgcolor=ft.Colors.GREY_900,
                                border_radius=12,
                            ),
                        ],
                    )
                )

            painel_materia = ft.ExpansionTile(
                title=ft.Text(materia["nome"], weight=ft.FontWeight.W_600),
                subtitle=ft.Row(
                    controls=[
                        ft.Text(f"{len(materia['topicos'])} tópico(s)", size=12, color=ft.Colors.GREY_400),
                        ft.TextButton(
                            "Registrar Questões (geral da matéria)",
                            icon=ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED,
                            on_click=lambda e, mid=materia["id"], nome=materia["nome"]: (
                                abrir_dialogo_rendimento(mid, None, f"{nome} (geral)")
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CALENDAR_TODAY,
                            icon_size=18,
                            tooltip="Agendar Bloco de Estudo",
                            on_click=lambda e, nome=materia["nome"]: (
                                abrir_dialogo_agendamento(f"{nome} (geral)")
                            ),
                        ),
                    ],
                ),
                controls=[ft.Container(padding=ft.Padding.only(left=20), content=ft.Column(linhas_topicos))],
                expanded=False,
            )
            lista_topicos.controls.append(painel_materia)

        page.update()

    def selecionar_edital(edital_id_str: str) -> None:
        if not edital_id_str:
            return
        edital_id = int(edital_id_str)
        estado["edital_id_ativo"] = edital_id
        construir_arvore_edital(edital_id)
        atualizar_cards_dashboard()
        atualizar_indicador_pdf()
        atualizar_painel_estudos_extra()
        page.update()

    # --- Importação/vinculação de arquivos via FilePicker --------------------------
    # Nota: a partir das versões recentes do Flet, FilePicker.pick_files() é
    # assíncrono e retorna a lista de arquivos diretamente (não existe mais
    # o parâmetro/evento `on_result`).
    #
    # IMPORTANTE: usamos DOIS FilePickers COMPLETAMENTE ISOLADOS — um para o
    # JSON do edital, outro para o PDF do edital — cada um com seu próprio
    # `allowed_extensions`. Reaproveitar uma única instância entre os dois
    # fluxos foi a causa do bug em que o filtro de extensão de um (ex: só
    # aceitar .json) "vazava" e escondia os arquivos .pdf no outro seletor.
    # Nenhum dos dois vai para page.overlay: FilePicker é um Service control
    # (não visual) e se registra automaticamente na página ao ser
    # instanciado — colocá-lo no overlay é o que causa "Unknown control".

    def processar_arquivo_importado(caminho_arquivo: str) -> None:
        """Lógica de importação do JSON do edital, reaproveitada pelo handler assíncrono."""
        try:
            resumo = db.importar_edital_json(caminho_arquivo)
            notificar(
                f"Edital '{resumo['concurso']}' importado! "
                f"{resumo['materias_inseridas']} matéria(s) e "
                f"{resumo['topicos_inseridos']} tópico(s) novo(s)."
            )
            carregar_editais_no_dropdown(selecionar_id=resumo["edital_id"])
        except FileNotFoundError:
            notificar("Arquivo não encontrado.", erro=True)
        except ValueError as ve:
            notificar(f"Erro no formato do JSON: {ve}", erro=True)
        except Exception as ex:
            notificar(f"Erro inesperado ao importar: {ex}", erro=True)

    file_picker_json = ft.FilePicker()

    async def ao_clicar_importar(e: ft.ControlEvent) -> None:
        arquivos = await file_picker_json.pick_files(
            dialog_title="Selecione o arquivo JSON do edital",
            allow_multiple=False,
            allowed_extensions=["json"],
        )
        if not arquivos:
            return  # Usuário cancelou a seleção.
        processar_arquivo_importado(arquivos[0].path)

    botao_importar = ft.Button(
        "Importar Edital (JSON)",
        icon=ft.Icons.UPLOAD_FILE,
        bgcolor=ft.Colors.BLUE_600,
        color=ft.Colors.WHITE,
        on_click=ao_clicar_importar,
    )

    # --- Vinculação do PDF oficial do edital (FilePicker isolado, .pdf) -----

    texto_pdf_vinculado = ft.Text("", size=12, color=ft.Colors.GREY_400)

    def remover_pdf_vinculado(e: ft.ControlEvent = None) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            return
        db.desvincular_pdf_edital(edital_id)
        notificar("PDF desvinculado do edital.")
        atualizar_indicador_pdf()
        page.update()

    botao_remover_pdf = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE,
        icon_color=ft.Colors.RED_300,
        icon_size=16,
        tooltip="Desvincular PDF",
        visible=False,
        on_click=remover_pdf_vinculado,
    )

    def atualizar_indicador_pdf() -> None:
        """Atualiza o texto que mostra qual PDF (se algum) está vinculado ao edital ativo."""
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            texto_pdf_vinculado.value = ""
            botao_remover_pdf.visible = False
            return
        caminho = db.obter_pdf_edital(edital_id)
        if caminho:
            nome_arquivo = os.path.basename(caminho)
            texto_pdf_vinculado.value = f"📄 PDF vinculado: {nome_arquivo}"
            botao_remover_pdf.visible = True
        else:
            texto_pdf_vinculado.value = "Nenhum PDF vinculado a este edital ainda."
            botao_remover_pdf.visible = False

    file_picker_pdf = ft.FilePicker()

    async def ao_clicar_vincular_pdf(e: ft.ControlEvent) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo antes de vincular o PDF.", erro=True)
            return

        arquivos = await file_picker_pdf.pick_files(
            dialog_title="Selecione o PDF oficial do edital",
            allow_multiple=False,
            allowed_extensions=["pdf"],
        )
        if not arquivos:
            return  # Usuário cancelou a seleção.

        caminho_pdf = arquivos[0].path
        try:
            db.vincular_pdf_edital(edital_id, caminho_pdf)
            notificar("Edital em PDF vinculado com sucesso!")
            atualizar_indicador_pdf()
        except ValueError as ve:
            notificar(str(ve), erro=True)
        except Exception as ex:
            notificar(f"Erro inesperado ao vincular o PDF: {ex}", erro=True)
        page.update()

    botao_vincular_pdf = ft.Button(
        "Vincular Edital em PDF",
        icon=ft.Icons.PICTURE_AS_PDF,
        bgcolor=ft.Colors.RED_700,
        color=ft.Colors.WHITE,
        on_click=ao_clicar_vincular_pdf,
    )

    # --- Importação de edital via PDF com IA (Gemini lê o PDF nativamente) --
    # Resolve o caso comum de editais 100% em PDF (inclusive "verticalizados"
    # baseados em imagem, sem camada de texto extraível) — em vez de exigir
    # um JSON montado manualmente, o Gemini lê o PDF direto e monta a
    # estrutura de matérias/tópicos, que é importada automaticamente.

    progress_ring_importar_pdf_ia = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)

    async def ao_clicar_importar_pdf_ia(e: ft.ControlEvent) -> None:
        arquivos = await file_picker_pdf.pick_files(
            dialog_title="Selecione o PDF do edital para a IA ler",
            allow_multiple=False,
            allowed_extensions=["pdf"],
        )
        if not arquivos:
            return  # Usuário cancelou a seleção.

        caminho_pdf = arquivos[0].path

        # A leitura do PDF pelo Gemini envolve rede e pode demorar alguns
        # segundos — roda em thread separada para não travar a UI do Flet.
        botao_importar_pdf_ia.disabled = True
        progress_ring_importar_pdf_ia.visible = True
        page.update()

        def tarefa_em_background() -> None:
            try:
                estrutura = ai_service.extrair_estrutura_edital_pdf(caminho_pdf)
                resumo = db.importar_edital_dict(estrutura)
                notificar(
                    f"Edital '{resumo['concurso']}' importado via IA! "
                    f"{resumo['materias_inseridas']} matéria(s) e "
                    f"{resumo['topicos_inseridos']} tópico(s) novo(s)."
                )
                carregar_editais_no_dropdown(selecionar_id=resumo["edital_id"])

            except FileNotFoundError:
                notificar("Arquivo PDF não encontrado.", erro=True)
            except ai_service.ApiKeyNaoConfiguradaError:
                notificar(
                    "Configure a Google AI Studio API Key na aba Configurações "
                    "antes de importar um edital via PDF.",
                    erro=True,
                )
            except ai_service.ApiKeyInvalidaError as ea:
                notificar(str(ea), erro=True)
            except ai_service.ErroAnaliseIA as ea:
                notificar(f"Não foi possível interpretar o PDF: {ea}", erro=True)
            except ValueError as ve:
                notificar(str(ve), erro=True)
            except Exception as ex:
                notificar(f"Erro inesperado ao importar o edital via PDF: {ex}", erro=True)
            finally:
                botao_importar_pdf_ia.disabled = False
                progress_ring_importar_pdf_ia.visible = False
                page.update()

        threading.Thread(target=tarefa_em_background, daemon=True).start()

    botao_importar_pdf_ia = ft.Button(
        "Importar Edital via PDF (IA)",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor=ft.Colors.PURPLE_700,
        color=ft.Colors.WHITE,
        on_click=ao_clicar_importar_pdf_ia,
    )

    # --- Cards: dias até a prova, meta diária e streak -----------------------

    def _criar_card_estudos(titulo: str, icone: str, cor: str, controle_valor: ft.Text) -> ft.Container:
        return ft.Container(
            expand=True,
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(icone, color=cor, size=20),
                            ft.Text(titulo, color=ft.Colors.GREY_400, size=13),
                        ],
                    ),
                    controle_valor,
                ],
            ),
        )

    def formatar_data_br_estudos(data_iso: str) -> str:
        try:
            return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return data_iso

    texto_dias_restantes = ft.Text("--", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)
    texto_meta_diaria_card = ft.Text("--", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300)
    texto_streak_estudos = ft.Text("--", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400)

    linha_cards_estudos = ft.Row(
        spacing=16,
        controls=[
            _criar_card_estudos(
                "Dias até a prova", ft.Icons.CALENDAR_TODAY, ft.Colors.AMBER_300, texto_dias_restantes,
            ),
            _criar_card_estudos(
                "Meta de hoje", ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED, ft.Colors.BLUE_300, texto_meta_diaria_card,
            ),
            _criar_card_estudos(
                "Sequência de dias", ft.Icons.TRENDING_UP, ft.Colors.GREEN_400, texto_streak_estudos,
            ),
        ],
    )

    # --- Diálogo: Configurar Prova (data + capacidade diária) ----------------

    campo_data_prova = ft.TextField(label="Data da prova", hint_text="DD/MM/AAAA")
    campo_capacidade_diaria = ft.TextField(
        label="Capacidade diária de estudo (minutos)",
        hint_text="Ex: 120",
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )

    def fechar_dialogo_config_prova(e: ft.ControlEvent = None) -> None:
        dialogo_config_prova.open = False
        page.update()

    def abrir_dialogo_config_prova(e: ft.ControlEvent = None) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return
        config = db.obter_config_prova(edital_id)
        campo_data_prova.value = (
            datetime.strptime(config["data_prova"], "%Y-%m-%d").strftime("%d/%m/%Y")
            if config["data_prova"] else ""
        )
        campo_capacidade_diaria.value = str(config["capacidade_diaria_min"])
        dialogo_config_prova.open = True
        page.update()

    def salvar_config_prova(e: ft.ControlEvent) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return

        texto_data = (campo_data_prova.value or "").strip()
        data_iso = None
        if texto_data:
            try:
                data_iso = datetime.strptime(texto_data, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                notificar("Data inválida. Utilize DD/MM/AAAA.", erro=True)
                return

        try:
            capacidade = int((campo_capacidade_diaria.value or "0").strip())
            db.atualizar_config_prova(edital_id, data_iso, capacidade)
        except ValueError as ve:
            notificar(str(ve) or "Capacidade inválida.", erro=True)
            return

        fechar_dialogo_config_prova()
        atualizar_painel_estudos_extra()
        notificar("Configuração da prova atualizada!")

    botao_configurar_prova = ft.Button(
        "Configurar Prova",
        icon=ft.Icons.SETTINGS,
        on_click=abrir_dialogo_config_prova,
    )

    dialogo_config_prova = ft.AlertDialog(
        modal=True,
        title=ft.Text("Configurar Prova"),
        content=ft.Column(tight=True, controls=[campo_data_prova, campo_capacidade_diaria]),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_config_prova),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_config_prova),
        ],
    )

    # --- Meta diária de questões ----------------------------------------------

    campo_meta_diaria_input = ft.TextField(
        label="Meta de questões hoje",
        width=200,
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )

    def salvar_meta_diaria(e: ft.ControlEvent) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return

        try:
            meta = int((campo_meta_diaria_input.value or "0").strip())
            db.definir_meta_diaria(edital_id, datetime.now().strftime("%Y-%m-%d"), meta)
        except ValueError as ve:
            notificar(str(ve) or "Informe uma meta válida.", erro=True)
            return

        campo_meta_diaria_input.value = ""
        atualizar_painel_estudos_extra()
        notificar("Meta de hoje definida!")

    botao_salvar_meta_diaria = ft.Button(
        "Definir Meta de Hoje",
        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
        on_click=salvar_meta_diaria,
    )

    # --- Cronograma dinâmico ---------------------------------------------------

    lista_cronograma_view = ft.ListView(expand=True, spacing=8, padding=10)

    estado_item_cronograma = {"item_id": None}
    campo_fonte_estudo_cronograma = ft.TextField(
        label="Fonte de estudo", hint_text="Ex: Gran Concursos - Aula 5, NotebookLM",
    )
    campo_notas_cronograma = ft.TextField(label="Notas", multiline=True, min_lines=2, max_lines=4)

    def fechar_dialogo_fonte_cronograma(e: ft.ControlEvent = None) -> None:
        dialogo_fonte_cronograma.open = False
        page.update()

    def abrir_dialogo_fonte_cronograma(item_id: int, fonte_atual: str, notas_atual: str) -> None:
        estado_item_cronograma["item_id"] = item_id
        campo_fonte_estudo_cronograma.value = fonte_atual or ""
        campo_notas_cronograma.value = notas_atual or ""
        dialogo_fonte_cronograma.open = True
        page.update()

    def salvar_fonte_cronograma(e: ft.ControlEvent) -> None:
        db.atualizar_item_cronograma(
            estado_item_cronograma["item_id"],
            fonte_estudo=(campo_fonte_estudo_cronograma.value or "").strip(),
            notas=(campo_notas_cronograma.value or "").strip(),
        )
        fechar_dialogo_fonte_cronograma()
        atualizar_painel_estudos_extra()
        notificar("Anotações salvas!")

    dialogo_fonte_cronograma = ft.AlertDialog(
        modal=True,
        title=ft.Text("Fonte de Estudo / Notas"),
        content=ft.Column(tight=True, controls=[campo_fonte_estudo_cronograma, campo_notas_cronograma]),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_fonte_cronograma),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_fonte_cronograma),
        ],
    )

    def alternar_status_item_cronograma(item_id: int, concluido: bool) -> None:
        novo_status = db.STATUS_CRONOGRAMA_CONCLUIDO if concluido else db.STATUS_CRONOGRAMA_PENDENTE
        db.atualizar_item_cronograma(item_id, status=novo_status)
        atualizar_painel_estudos_extra()

    def gerar_cronograma_ui(e: ft.ControlEvent = None) -> None:
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo primeiro.", erro=True)
            return
        try:
            qtd = db.gerar_cronograma(edital_id)
        except ValueError as ve:
            notificar(str(ve), erro=True)
            return
        atualizar_painel_estudos_extra()
        notificar(f"Cronograma gerado! {qtd} bloco(s) de estudo distribuídos até a prova.")

    botao_gerar_cronograma = ft.Button(
        "Gerar/Regerar Cronograma",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor=ft.Colors.PURPLE_700,
        color=ft.Colors.WHITE,
        on_click=gerar_cronograma_ui,
    )

    def atualizar_painel_estudos_extra() -> None:
        """Atualiza os cards (dias restantes, meta diária, streak) e a lista de cronograma."""
        edital_id = estado["edital_id_ativo"]

        if not edital_id:
            texto_dias_restantes.value = "--"
            texto_meta_diaria_card.value = "--"
            texto_streak_estudos.value = "--"
            lista_cronograma_view.controls.clear()
            page.update()
            return

        dias = db.calcular_dias_restantes_prova(edital_id)
        if dias is None:
            texto_dias_restantes.value = "Não definida"
        elif dias < 0:
            texto_dias_restantes.value = "Prova já passou"
        elif dias == 0:
            texto_dias_restantes.value = "É hoje!"
        else:
            texto_dias_restantes.value = f"{dias} dia{'s' if dias != 1 else ''}"

        hoje_str = datetime.now().strftime("%Y-%m-%d")
        meta_info = db.obter_meta_diaria(edital_id, hoje_str)
        texto_meta_diaria_card.value = (
            f"{meta_info['questoes_feitas']}/{meta_info['meta_questoes']}"
            if meta_info["meta_questoes"] > 0
            else f"{meta_info['questoes_feitas']} (sem meta)"
        )

        streak = db.calcular_streak_meta_diaria(edital_id)
        texto_streak_estudos.value = f"{streak} dia{'s' if streak != 1 else ''}"

        lista_cronograma_view.controls.clear()

        config = db.obter_config_prova(edital_id)
        data_fim = config["data_prova"] or (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        itens = db.listar_cronograma_periodo(edital_id, hoje_str, data_fim)

        if not itens:
            lista_cronograma_view.controls.append(
                ft.Text(
                    "Nenhum item de cronograma. Configure a data da prova e clique em "
                    "'Gerar/Regerar Cronograma'.",
                    italic=True, color=ft.Colors.GREY_500,
                )
            )
            page.update()
            return

        dia_atual_rotulo = None
        for item in itens:
            if item["data"] != dia_atual_rotulo:
                dia_atual_rotulo = item["data"]
                rotulo = "Hoje" if item["data"] == hoje_str else formatar_data_br_estudos(item["data"])
                lista_cronograma_view.controls.append(
                    ft.Text(rotulo, weight=ft.FontWeight.BOLD, size=14, color=ft.Colors.AMBER_300)
                )

            concluido = item["status"] == db.STATUS_CRONOGRAMA_CONCLUIDO
            assunto = item["topico_nome"] or f"{item['materia_nome']} (geral)"

            lista_cronograma_view.controls.append(
                ft.Container(
                    padding=12,
                    border_radius=10,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    content=ft.Row(
                        controls=[
                            ft.Checkbox(
                                value=concluido,
                                on_change=lambda e, iid=item["id"]: alternar_status_item_cronograma(
                                    iid, e.control.value
                                ),
                            ),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(f"{item['materia_nome']} — {assunto}", size=13),
                                    ft.Text(
                                        f"{item['tipo_atividade']} • {item['tempo_estimado_min']} min"
                                        + (f" • {item['fonte_estudo']}" if item["fonte_estudo"] else ""),
                                        size=11, color=ft.Colors.GREY_400,
                                    ),
                                ],
                            ),
                            ft.IconButton(
                                icon=ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED,
                                icon_size=18,
                                tooltip="Fonte de estudo / notas",
                                on_click=lambda e, iid=item["id"], fo=item["fonte_estudo"], no=item["notas"]: (
                                    abrir_dialogo_fonte_cronograma(iid, fo, no)
                                ),
                            ),
                        ],
                    ),
                )
            )

        page.update()

    aba_estudos = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=16,
            expand=True,
            controls=[
                ft.Text("Estudos & Editais", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row(
                    controls=[
                        botao_importar,
                        botao_vincular_pdf,
                        botao_importar_pdf_ia,
                        progress_ring_importar_pdf_ia,
                    ]
                ),
                ft.Row(controls=[dropdown_editais, botao_excluir_edital]),
                ft.Row(controls=[texto_pdf_vinculado, botao_remover_pdf]),
                ft.Divider(),
                linha_cards_estudos,
                ft.Row(
                    spacing=12,
                    controls=[
                        botao_configurar_prova,
                        campo_meta_diaria_input,
                        botao_salvar_meta_diaria,
                        botao_gerar_cronograma,
                    ],
                ),
                ft.Container(
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=8,
                    padding=10,
                    content=ft.Row(
                        expand=True,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                        controls=[
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    expand=True,
                                    controls=[
                                        ft.Text("Matérias e Tópicos", weight=ft.FontWeight.BOLD, size=14),
                                        lista_topicos,
                                    ],
                                ),
                            ),
                            ft.VerticalDivider(),
                            ft.Container(
                                expand=True,
                                content=ft.Column(
                                    expand=True,
                                    controls=[
                                        ft.Text("Cronograma", weight=ft.FontWeight.BOLD, size=14),
                                        lista_cronograma_view,
                                    ],
                                ),
                            ),
                        ],
                    ),
                ),
            ],
        ),
    )

    # ===================================================================
    # ABA: DASHBOARD
    # ===================================================================

    def criar_card(titulo: str, icone: str, cor: str, controles_valor: list) -> ft.Container:
        """Monta um card visual padronizado (cantos arredondados) para o Dashboard."""
        return ft.Container(
            width=280,
            padding=20,
            border_radius=16,
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(icone, color=cor, size=20),
                            ft.Text(titulo, color=ft.Colors.GREY_400, size=13),
                        ],
                    ),
                    *controles_valor,
                ],
            ),
        )

    # --- Card 1: Total de editais cadastrados -----------------------------
    texto_total_editais = ft.Text("0", size=32, weight=ft.FontWeight.BOLD)
    card_total_editais = criar_card(
        "Editais Cadastrados",
        ft.Icons.LIBRARY_BOOKS_OUTLINED,
        ft.Colors.BLUE_400,
        [texto_total_editais],
    )

    # --- Card 2: Progresso geral do edital selecionado ---------------------
    texto_progresso_geral = ft.Text("0%", size=32, weight=ft.FontWeight.BOLD)
    texto_progresso_sub = ft.Text("Nenhum edital selecionado", size=12, color=ft.Colors.GREY_500)
    card_progresso_geral = criar_card(
        "Progresso Geral",
        ft.Icons.TRENDING_UP,
        ft.Colors.GREEN_400,
        [texto_progresso_geral, texto_progresso_sub],
    )

    def atualizar_cards_dashboard() -> None:
        """Recalcula os números exibidos nos cards a partir do banco de dados."""
        editais = db.listar_editais()
        texto_total_editais.value = str(len(editais))

        edital_id = estado["edital_id_ativo"]
        if edital_id:
            stats = db.contar_estatisticas_edital(edital_id)
            total = stats["total_topicos"]
            vistos = stats["topicos_vistos"]
            percentual = round((vistos / total) * 100, 1) if total else 0.0
            edital = db.obter_edital_por_id(edital_id)

            texto_progresso_geral.value = f"{percentual}%"
            texto_progresso_sub.value = (
                f"{edital['nome']} — {vistos}/{total} tópicos" if edital else ""
            )
        else:
            texto_progresso_geral.value = "0%"
            texto_progresso_sub.value = "Nenhum edital selecionado"

        page.update()

    # --- Painel "Análise do Mentor IA" -------------------------------------

    progress_ring_ia = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)

    markdown_resultado_ia = ft.Markdown(
        value="_Clique em **Gerar Diagnóstico com Gemini** para receber um plano de ataque "
              "personalizado com base no seu progresso no edital selecionado._",
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
    )

    def gerar_diagnostico_ia(e: ft.ControlEvent) -> None:
        """
        Dispara a análise de IA em uma thread separada, para não travar a UI
        do Flet enquanto aguarda a resposta do Gemini.
        """
        edital_id = estado["edital_id_ativo"]
        if not edital_id:
            notificar("Selecione um edital ativo na aba 'Estudos & Editais' primeiro.", erro=True)
            return

        # Estado de "carregando": desabilita o botão e exibe o ProgressRing.
        botao_gerar_diagnostico.disabled = True
        progress_ring_ia.visible = True
        markdown_resultado_ia.value = "_Consultando o Gemini, aguarde..._"
        page.update()

        def tarefa_em_background() -> None:
            try:
                resultado = ai_service.analisar_progresso_edital(edital_id)
                markdown_resultado_ia.value = resultado

            except (ai_service.ApiKeyNaoConfiguradaError, ai_service.ApiKeyInvalidaError):
                markdown_resultado_ia.value = (
                    "_Nenhuma análise gerada. Configure sua API Key para continuar._"
                )
                notificar(
                    "Por favor, configure uma Google API Key válida na aba Configurações.",
                    erro=True,
                )

            except ValueError as ve:
                markdown_resultado_ia.value = "_Nenhuma análise gerada._"
                notificar(str(ve), erro=True)

            except ai_service.ErroAnaliseIA as ea:
                markdown_resultado_ia.value = "_Nenhuma análise gerada. Tente novamente._"
                notificar(str(ea), erro=True)

            except Exception as ex:
                markdown_resultado_ia.value = "_Nenhuma análise gerada._"
                notificar(f"Erro inesperado ao gerar diagnóstico: {ex}", erro=True)

            finally:
                # Restaura o estado da UI independentemente do resultado.
                botao_gerar_diagnostico.disabled = False
                progress_ring_ia.visible = False
                page.update()

        threading.Thread(target=tarefa_em_background, daemon=True).start()

    botao_gerar_diagnostico = ft.Button(
        "Gerar Diagnóstico com Gemini",
        icon=ft.Icons.AUTO_AWESOME,
        bgcolor=ft.Colors.PURPLE_700,
        color=ft.Colors.WHITE,
        on_click=gerar_diagnostico_ia,
    )

    painel_ia = ft.Container(
        expand=True,
        padding=20,
        border_radius=16,
        bgcolor=ft.Colors.GREY_900,
        border=ft.Border.all(1, ft.Colors.GREY_800),
        content=ft.Column(
            expand=True,
            spacing=14,
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("Análise do Mentor IA", size=16, weight=ft.FontWeight.W_600),
                    ]
                ),
                ft.Row(spacing=12, controls=[botao_gerar_diagnostico, progress_ring_ia]),
                ft.Divider(),
                ft.Container(
                    expand=True,
                    content=ft.Column(
                        expand=True,
                        scroll=ft.ScrollMode.AUTO,
                        controls=[markdown_resultado_ia],
                    ),
                ),
            ],
        ),
    )

    aba_dashboard = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=20,
            expand=True,
            controls=[
                ft.Text("Dashboard", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                ft.Row(spacing=16, controls=[card_total_editais, card_progresso_geral]),
                painel_ia,
            ],
        ),
    )

    # ===================================================================
    # ABA: FACULDADE
    # ===================================================================

    lista_disciplinas_view = ft.ListView(expand=True, spacing=12, padding=10)

    campo_nome_disciplina = ft.TextField(label="Nome da Disciplina", autofocus=True)
    campo_professor_disciplina = ft.TextField(label="Professor")

    def fechar_dialogo_disciplina(e: ft.ControlEvent = None) -> None:
        dialogo_disciplina.open = False
        page.update()

    def abrir_dialogo_disciplina(e: ft.ControlEvent = None) -> None:
        campo_nome_disciplina.value = ""
        campo_professor_disciplina.value = ""
        dialogo_disciplina.open = True
        page.update()

    def salvar_disciplina(e: ft.ControlEvent) -> None:
        nome = (campo_nome_disciplina.value or "").strip()
        if not nome:
            notificar("Informe o nome da disciplina.", erro=True)
            return
        db.inserir_disciplina(nome, campo_professor_disciplina.value or "")
        fechar_dialogo_disciplina()
        notificar(f"Disciplina '{nome}' adicionada.")
        construir_lista_disciplinas()

    dialogo_disciplina = ft.AlertDialog(
        modal=True,
        title=ft.Text("Adicionar Disciplina", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            tight=True,
            spacing=12,
            controls=[campo_nome_disciplina, campo_professor_disciplina],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_disciplina),
            ft.Button(
                "Salvar",
                icon=ft.Icons.SAVE,
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
                on_click=salvar_disciplina,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def alterar_faltas(disciplina_id: int, delta: int) -> None:
        db.atualizar_faltas_disciplina(disciplina_id, delta)
        construir_lista_disciplinas()

    def salvar_notas_disciplina(
        disciplina_id: int, campo_m1: ft.TextField, campo_m2: ft.TextField
    ) -> None:
        try:
            m1 = float((campo_m1.value or "0").strip().replace(",", ".") or 0)
            m2 = float((campo_m2.value or "0").strip().replace(",", ".") or 0)
        except ValueError:
            notificar("Notas inválidas. Use apenas números (ex: 7.5).", erro=True)
            return
        media = db.atualizar_notas_disciplina(disciplina_id, m1, m2)
        notificar(f"Notas salvas. Nova média: {media}")
        construir_lista_disciplinas()

    def excluir_disciplina(disciplina_id: int) -> None:
        db.deletar_disciplina(disciplina_id)
        notificar("Disciplina removida.")
        construir_lista_disciplinas()

    def construir_lista_disciplinas() -> None:
        lista_disciplinas_view.controls.clear()
        disciplinas = db.listar_disciplinas()

        if not disciplinas:
            lista_disciplinas_view.controls.append(
                ft.Text("Nenhuma disciplina cadastrada ainda.", italic=True, color=ft.Colors.GREY_500)
            )
            page.update()
            return

        for d in disciplinas:
            campo_m1 = ft.TextField(
                label="M1",
                value=str(d["m1"]),
                width=80,
                input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True),
            )
            campo_m2 = ft.TextField(
                label="M2",
                value=str(d["m2"]),
                width=80,
                input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True),
            )
            cor_media = ft.Colors.GREEN_400 if d["media_final"] >= 7.0 else ft.Colors.RED_400

            card = ft.Container(
                padding=16,
                border_radius=14,
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    controls=[
                                        ft.Text(d["nome"], weight=ft.FontWeight.W_600, size=15),
                                        ft.Text(
                                            d["professor"] or "Sem professor definido",
                                            size=12,
                                            color=ft.Colors.GREY_500,
                                        ),
                                    ],
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_color=ft.Colors.RED_300,
                                    tooltip="Remover disciplina",
                                    on_click=lambda e, did=d["id"]: excluir_disciplina(did),
                                ),
                            ],
                        ),
                        ft.Row(
                            spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Row(
                                    spacing=2,
                                    controls=[
                                        ft.Text("Faltas:", size=12, color=ft.Colors.GREY_400),
                                        ft.IconButton(
                                            icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                                            icon_size=18,
                                            on_click=lambda e, did=d["id"]: alterar_faltas(did, -1),
                                        ),
                                        ft.Text(str(d["faltas"]), weight=ft.FontWeight.BOLD),
                                        ft.IconButton(
                                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                            icon_size=18,
                                            on_click=lambda e, did=d["id"]: alterar_faltas(did, +1),
                                        ),
                                    ],
                                ),
                                campo_m1,
                                campo_m2,
                                ft.IconButton(
                                    icon=ft.Icons.SAVE,
                                    tooltip="Salvar notas",
                                    on_click=lambda e, did=d["id"], cm1=campo_m1, cm2=campo_m2: (
                                        salvar_notas_disciplina(did, cm1, cm2)
                                    ),
                                ),
                                ft.Container(
                                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                                    bgcolor=ft.Colors.GREY_800,
                                    border_radius=10,
                                    content=ft.Text(
                                        f"Média: {d['media_final']}",
                                        color=cor_media,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
            )
            lista_disciplinas_view.controls.append(card)

        page.update()

    aba_faculdade = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=16,
            expand=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Faculdade", size=24, weight=ft.FontWeight.BOLD),
                        ft.Button(
                            "Adicionar Disciplina",
                            icon=ft.Icons.ADD,
                            bgcolor=ft.Colors.BLUE_600,
                            color=ft.Colors.WHITE,
                            on_click=abrir_dialogo_disciplina,
                        ),
                    ],
                ),
                ft.Divider(),
                ft.Container(
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=8,
                    padding=10,
                    content=lista_disciplinas_view,
                ),
            ],
        ),
    )

    # ===================================================================
    # ABA: CLIENTES & FREELAS
    # ===================================================================

    OPCOES_STATUS_PROJETO = ["Em Andamento", "Concluído", "Aguardando Pagamento"]

    lista_projetos_view = ft.ListView(expand=True, spacing=12, padding=10)

    campo_nome_projeto = ft.TextField(label="Nome do Projeto", autofocus=True)
    campo_cliente_projeto = ft.TextField(label="Cliente")
    campo_prazo_projeto = ft.TextField(label="Prazo", hint_text="DD/MM/AAAA")
    campo_valor_projeto = ft.TextField(
        label="Valor (R$)",
        input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True),
    )
    dropdown_status_novo_projeto = ft.Dropdown(
        label="Status",
        value=OPCOES_STATUS_PROJETO[0],
        options=[ft.dropdown.Option(key=s, text=s) for s in OPCOES_STATUS_PROJETO],
    )

    def fechar_dialogo_projeto(e: ft.ControlEvent = None) -> None:
        dialogo_projeto.open = False
        page.update()

    def abrir_dialogo_projeto(e: ft.ControlEvent = None) -> None:
        campo_nome_projeto.value = ""
        campo_cliente_projeto.value = ""
        campo_prazo_projeto.value = ""
        campo_valor_projeto.value = ""
        dropdown_status_novo_projeto.value = OPCOES_STATUS_PROJETO[0]
        dialogo_projeto.open = True
        page.update()

    def salvar_projeto(e: ft.ControlEvent) -> None:
        nome = (campo_nome_projeto.value or "").strip()
        if not nome:
            notificar("Informe o nome do projeto.", erro=True)
            return
        try:
            valor = float((campo_valor_projeto.value or "0").strip().replace(",", ".") or 0)
        except ValueError:
            notificar("Valor inválido. Use apenas números (ex: 1500.00).", erro=True)
            return

        db.inserir_projeto(
            nome_projeto=nome,
            cliente=campo_cliente_projeto.value or "",
            prazo=campo_prazo_projeto.value or "",
            valor=valor,
            status=dropdown_status_novo_projeto.value,
        )
        fechar_dialogo_projeto()
        notificar(f"Projeto '{nome}' adicionado.")
        construir_lista_projetos()

    dialogo_projeto = ft.AlertDialog(
        modal=True,
        title=ft.Text("Novo Projeto", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            tight=True,
            spacing=12,
            controls=[
                campo_nome_projeto,
                campo_cliente_projeto,
                campo_prazo_projeto,
                campo_valor_projeto,
                dropdown_status_novo_projeto,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_projeto),
            ft.Button(
                "Salvar Projeto",
                icon=ft.Icons.SAVE,
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
                on_click=salvar_projeto,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def alterar_status_projeto_ui(projeto_id: int, novo_status: str) -> None:
        db.atualizar_status_projeto(projeto_id, novo_status)
        notificar(f"Status atualizado para '{novo_status}'.")
        construir_lista_projetos()

    def excluir_projeto(projeto_id: int) -> None:
        db.deletar_projeto(projeto_id)
        notificar("Projeto removido.")
        construir_lista_projetos()

    def construir_lista_projetos() -> None:
        lista_projetos_view.controls.clear()
        projetos = db.listar_projetos()

        if not projetos:
            lista_projetos_view.controls.append(
                ft.Text("Nenhum projeto cadastrado ainda.", italic=True, color=ft.Colors.GREY_500)
            )
            page.update()
            return

        for p in projetos:
            valor_formatado = f"R$ {p['valor']:.2f}"
            dropdown_status = ft.Dropdown(
                value=p["status"] if p["status"] in OPCOES_STATUS_PROJETO else OPCOES_STATUS_PROJETO[0],
                width=210,
                options=[ft.dropdown.Option(key=s, text=s) for s in OPCOES_STATUS_PROJETO],
                on_select=lambda e, pid=p["id"]: alterar_status_projeto_ui(pid, e.control.value),
            )
            card = ft.Container(
                padding=16,
                border_radius=14,
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Column(
                            spacing=2,
                            expand=True,
                            controls=[
                                ft.Text(p["nome_projeto"], weight=ft.FontWeight.W_600, size=15),
                                ft.Text(
                                    f"Cliente: {p['cliente'] or '—'}   |   Prazo: {p['prazo'] or '—'}",
                                    size=12,
                                    color=ft.Colors.GREY_500,
                                ),
                                ft.Text(
                                    valor_formatado,
                                    size=13,
                                    color=ft.Colors.GREEN_300,
                                    weight=ft.FontWeight.BOLD,
                                ),
                            ],
                        ),
                        dropdown_status,
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            icon_color=ft.Colors.RED_300,
                            tooltip="Remover projeto",
                            on_click=lambda e, pid=p["id"]: excluir_projeto(pid),
                        ),
                    ],
                ),
            )
            lista_projetos_view.controls.append(card)

        page.update()

    aba_clientes = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=16,
            expand=True,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Clientes & Freelas", size=24, weight=ft.FontWeight.BOLD),
                        ft.Button(
                            "Novo Projeto",
                            icon=ft.Icons.ADD,
                            bgcolor=ft.Colors.BLUE_600,
                            color=ft.Colors.WHITE,
                            on_click=abrir_dialogo_projeto,
                        ),
                    ],
                ),
                ft.Divider(),
                ft.Container(
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=8,
                    padding=10,
                    content=lista_projetos_view,
                ),
            ],
        ),
    )

    # ===================================================================
    # ABA: ROTINA & HÁBITOS
    # ===================================================================

    DIAS_ROTINA_LABELS = [
        ("segunda", "Seg"), ("terca", "Ter"), ("quarta", "Qua"), ("quinta", "Qui"),
        ("sexta", "Sex"), ("sabado", "Sáb"), ("domingo", "Dom"),
    ]

    CORES_PRIORIDADE = {
        db.PRIORIDADE_ALTA: ft.Colors.RED_300,
        db.PRIORIDADE_MEDIA: ft.Colors.AMBER_300,
        db.PRIORIDADE_BAIXA: ft.Colors.GREEN_300,
    }

    def formatar_data_br_rotina(data_iso: Optional[str]) -> str:
        if not data_iso:
            return ""
        try:
            return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return data_iso

    # --- Sub-seção: Hábitos Fixos ---------------------------------------------

    tabela_habitos = ft.DataTable(
        columns=(
            [ft.DataColumn(ft.Text("Hábito")), ft.DataColumn(ft.Text("Horário"))]
            + [ft.DataColumn(ft.Text(label)) for _, label in DIAS_ROTINA_LABELS]
            + [ft.DataColumn(ft.Text(""))]
        ),
        rows=[],
    )

    campo_nome_habito = ft.TextField(
        label="Nome do Hábito", hint_text='ex: "Beber 3L de água"', autofocus=True
    )
    campo_horario_habito_novo = ft.TextField(
        label="Horário sugerido (opcional)", hint_text="HH:MM",
    )

    def fechar_dialogo_habito(e: ft.ControlEvent = None) -> None:
        dialogo_habito.open = False
        page.update()

    def abrir_dialogo_habito(e: ft.ControlEvent = None) -> None:
        campo_nome_habito.value = ""
        campo_horario_habito_novo.value = ""
        dialogo_habito.open = True
        page.update()

    def salvar_habito(e: ft.ControlEvent) -> None:
        nome = (campo_nome_habito.value or "").strip()
        if not nome:
            notificar("Informe o nome do hábito.", erro=True)
            return

        horario = (campo_horario_habito_novo.value or "").strip()
        if horario:
            try:
                datetime.strptime(horario, "%H:%M")
            except ValueError:
                notificar("Horário inválido. Utilize HH:MM.", erro=True)
                return

        db.inserir_habito(nome, horario)
        fechar_dialogo_habito()
        notificar(f"Hábito '{nome}' adicionado.")
        construir_tabela_habitos()

    dialogo_habito = ft.AlertDialog(
        modal=True,
        title=ft.Text("Adicionar Hábito", weight=ft.FontWeight.BOLD),
        content=ft.Column(
            tight=True, spacing=12, controls=[campo_nome_habito, campo_horario_habito_novo],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_habito),
            ft.Button(
                "Salvar",
                icon=ft.Icons.SAVE,
                bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE,
                on_click=salvar_habito,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def alternar_dia_habito(habito_id: int, dia: str, valor: bool) -> None:
        """Persiste o novo estado do checkbox direto no SQLite (0/1)."""
        db.atualizar_dia_habito(habito_id, dia, valor)

    def excluir_habito(habito_id: int) -> None:
        db.deletar_habito(habito_id)
        notificar("Hábito removido.")
        construir_tabela_habitos()

    def salvar_horario_habito_inline(habito_id: int, valor: str) -> None:
        valor = (valor or "").strip()
        if valor:
            try:
                datetime.strptime(valor, "%H:%M")
            except ValueError:
                notificar("Horário inválido. Utilize HH:MM.", erro=True)
                return
        db.atualizar_horario_habito(habito_id, valor)
        notificar("Horário atualizado.")

    def construir_tabela_habitos() -> None:
        habitos = db.listar_habitos()
        linhas = []

        for h in habitos:
            celulas = [
                ft.DataCell(ft.Text(h["nome_habito"])),
                ft.DataCell(
                    ft.TextField(
                        value=h["horario"] or "",
                        hint_text="HH:MM",
                        width=80,
                        on_blur=lambda e, hid=h["id"]: salvar_horario_habito_inline(hid, e.control.value),
                    )
                ),
            ]
            for dia_chave, _ in DIAS_ROTINA_LABELS:
                celulas.append(
                    ft.DataCell(
                        ft.Checkbox(
                            value=bool(h[dia_chave]),
                            on_change=lambda e, hid=h["id"], dia=dia_chave: (
                                alternar_dia_habito(hid, dia, e.control.value)
                            ),
                        )
                    )
                )
            celulas.append(
                ft.DataCell(
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_300,
                        icon_size=18,
                        tooltip="Remover hábito",
                        on_click=lambda e, hid=h["id"]: excluir_habito(hid),
                    )
                )
            )
            linhas.append(ft.DataRow(cells=celulas))

        if not linhas:
            linhas = [
                ft.DataRow(
                    cells=[ft.DataCell(ft.Text("Nenhum hábito cadastrado ainda.", italic=True))]
                    + [ft.DataCell(ft.Text(""))]
                    + [ft.DataCell(ft.Text("")) for _ in DIAS_ROTINA_LABELS]
                    + [ft.DataCell(ft.Text(""))]
                )
            ]

        tabela_habitos.rows = linhas
        page.update()

    tela_habitos_fixos = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Adicionar Hábito",
                        icon=ft.Icons.ADD,
                        bgcolor=ft.Colors.BLUE_600,
                        color=ft.Colors.WHITE,
                        on_click=abrir_dialogo_habito,
                    ),
                ],
            ),
            ft.Container(
                expand=True,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=8,
                padding=10,
                content=ft.Column(
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                    controls=[tabela_habitos],
                ),
            ),
        ],
    )

    # --- Sub-seção: Tarefas / Extras (compartilham o mesmo backend) ----------

    lista_tarefas_view = ft.ListView(expand=True, spacing=8, padding=10)
    lista_extras_view = ft.ListView(expand=True, spacing=8, padding=10)

    estado_nova_tarefa = {"origem": db.ORIGEM_TAREFA_PLANEJADA}

    texto_titulo_dialogo_tarefa = ft.Text("Nova Tarefa", weight=ft.FontWeight.BOLD)
    campo_titulo_tarefa = ft.TextField(label="Título", autofocus=True)
    campo_descricao_tarefa = ft.TextField(label="Descrição (opcional)", multiline=True, min_lines=2, max_lines=4)
    campo_data_tarefa = ft.TextField(label="Data (opcional)", hint_text="DD/MM/AAAA")
    campo_horario_tarefa = ft.TextField(label="Horário (opcional)", hint_text="HH:MM")
    dropdown_prioridade_tarefa = ft.Dropdown(
        label="Prioridade",
        value=db.PRIORIDADE_MEDIA,
        options=[
            ft.dropdown.Option(key=db.PRIORIDADE_ALTA, text="Alta"),
            ft.dropdown.Option(key=db.PRIORIDADE_MEDIA, text="Média"),
            ft.dropdown.Option(key=db.PRIORIDADE_BAIXA, text="Baixa"),
        ],
    )

    def fechar_dialogo_tarefa(e: ft.ControlEvent = None) -> None:
        dialogo_tarefa.open = False
        page.update()

    def abrir_dialogo_tarefa(origem: str) -> None:
        estado_nova_tarefa["origem"] = origem
        texto_titulo_dialogo_tarefa.value = (
            "Nova Tarefa" if origem == db.ORIGEM_TAREFA_PLANEJADA else "Nova Atividade Extra"
        )
        campo_titulo_tarefa.value = ""
        campo_descricao_tarefa.value = ""
        campo_data_tarefa.value = ""
        campo_horario_tarefa.value = ""
        dropdown_prioridade_tarefa.value = db.PRIORIDADE_MEDIA
        dialogo_tarefa.open = True
        page.update()

    def salvar_tarefa(e: ft.ControlEvent) -> None:
        titulo = (campo_titulo_tarefa.value or "").strip()
        if not titulo:
            notificar("Informe o título.", erro=True)
            return

        data_iso = None
        texto_data = (campo_data_tarefa.value or "").strip()
        if texto_data:
            try:
                data_iso = datetime.strptime(texto_data, "%d/%m/%Y").strftime("%Y-%m-%d")
            except ValueError:
                notificar("Data inválida. Utilize DD/MM/AAAA.", erro=True)
                return

        horario = (campo_horario_tarefa.value or "").strip()
        if horario:
            try:
                datetime.strptime(horario, "%H:%M")
            except ValueError:
                notificar("Horário inválido. Utilize HH:MM.", erro=True)
                return

        db.adicionar_tarefa(
            titulo=titulo,
            descricao=(campo_descricao_tarefa.value or "").strip(),
            data=data_iso,
            horario=horario,
            prioridade=dropdown_prioridade_tarefa.value,
            origem=estado_nova_tarefa["origem"],
        )

        fechar_dialogo_tarefa()
        notificar("Tarefa adicionada!")
        construir_lista_tarefas()
        construir_lista_extras()

    dialogo_tarefa = ft.AlertDialog(
        modal=True,
        title=texto_titulo_dialogo_tarefa,
        content=ft.Column(
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=340,
            controls=[
                campo_titulo_tarefa,
                campo_descricao_tarefa,
                campo_data_tarefa,
                campo_horario_tarefa,
                dropdown_prioridade_tarefa,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_tarefa),
            ft.Button(
                "Salvar", icon=ft.Icons.SAVE, bgcolor=ft.Colors.GREEN_700,
                color=ft.Colors.WHITE, on_click=salvar_tarefa,
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )

    def alternar_conclusao_tarefa(tarefa_id: int, concluida: bool) -> None:
        db.alternar_status_tarefa(tarefa_id, concluida)
        construir_lista_tarefas()
        construir_lista_extras()

    def excluir_tarefa_ui(tarefa_id: int) -> None:
        db.deletar_tarefa(tarefa_id)
        notificar("Tarefa removida.")
        construir_lista_tarefas()
        construir_lista_extras()

    def _construir_item_tarefa(tarefa: dict) -> ft.Container:
        concluida = tarefa["status"] == db.STATUS_TAREFA_CONCLUIDA
        cor_prioridade = CORES_PRIORIDADE.get(tarefa["prioridade"], ft.Colors.GREY_400)

        detalhes = []
        if tarefa["data"]:
            detalhes.append(formatar_data_br_rotina(tarefa["data"]))
        if tarefa["horario"]:
            detalhes.append(tarefa["horario"])
        if tarefa["descricao"]:
            detalhes.append(tarefa["descricao"])

        return ft.Container(
            padding=14,
            border_radius=12,
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            content=ft.Row(
                controls=[
                    ft.Checkbox(
                        value=concluida,
                        on_change=lambda e, tid=tarefa["id"]: alternar_conclusao_tarefa(tid, e.control.value),
                    ),
                    ft.Container(
                        content=ft.Text(tarefa["prioridade"], size=11, color=ft.Colors.GREY_900),
                        bgcolor=cor_prioridade,
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                        border_radius=12,
                    ),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(
                                tarefa["titulo"],
                                size=14,
                                weight=ft.FontWeight.W_600,
                                color=ft.Colors.GREY_500 if concluida else None,
                            ),
                            ft.Text(" • ".join(detalhes), size=11, color=ft.Colors.GREY_400)
                            if detalhes else ft.Container(),
                        ],
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_300,
                        icon_size=18,
                        tooltip="Excluir",
                        on_click=lambda e, tid=tarefa["id"]: excluir_tarefa_ui(tid),
                    ),
                ],
            ),
        )

    def construir_lista_tarefas() -> None:
        lista_tarefas_view.controls.clear()
        tarefas = db.listar_tarefas(origem=db.ORIGEM_TAREFA_PLANEJADA)

        if not tarefas:
            lista_tarefas_view.controls.append(
                ft.Text("Nenhuma tarefa cadastrada.", italic=True, color=ft.Colors.GREY_500)
            )
        else:
            for tarefa in tarefas:
                lista_tarefas_view.controls.append(_construir_item_tarefa(tarefa))

        page.update()

    def construir_lista_extras() -> None:
        lista_extras_view.controls.clear()
        extras = db.listar_tarefas(origem=db.ORIGEM_TAREFA_EXTRA)

        if not extras:
            lista_extras_view.controls.append(
                ft.Text("Nenhuma atividade extra registrada.", italic=True, color=ft.Colors.GREY_500)
            )
        else:
            for tarefa in extras:
                lista_extras_view.controls.append(_construir_item_tarefa(tarefa))

        page.update()

    tela_tarefas = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Nova Tarefa",
                        icon=ft.Icons.ADD,
                        bgcolor=ft.Colors.BLUE_600,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: abrir_dialogo_tarefa(db.ORIGEM_TAREFA_PLANEJADA),
                    ),
                ],
            ),
            ft.Container(
                expand=True,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=10,
                padding=10,
                content=lista_tarefas_view,
            ),
        ],
    )

    tela_extras = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Nova Atividade Extra",
                        icon=ft.Icons.ADD,
                        bgcolor=ft.Colors.AMBER_700,
                        color=ft.Colors.WHITE,
                        on_click=lambda e: abrir_dialogo_tarefa(db.ORIGEM_TAREFA_EXTRA),
                    ),
                ],
            ),
            ft.Container(
                expand=True,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                border_radius=10,
                padding=10,
                content=lista_extras_view,
            ),
        ],
    )

    # --- Seletor de sub-seções e montagem final da aba ------------------------

    conteudo_rotina = ft.Container(expand=True, content=tela_habitos_fixos)

    def mostrar_habitos_fixos(e: ft.ControlEvent = None) -> None:
        construir_tabela_habitos()
        conteudo_rotina.content = tela_habitos_fixos
        page.update()

    def mostrar_tarefas(e: ft.ControlEvent = None) -> None:
        construir_lista_tarefas()
        conteudo_rotina.content = tela_tarefas
        page.update()

    def mostrar_extras(e: ft.ControlEvent = None) -> None:
        construir_lista_extras()
        conteudo_rotina.content = tela_extras
        page.update()

    linha_seletor_rotina = ft.Row(
        spacing=12,
        controls=[
            ft.Button("📋 Hábitos Fixos", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, on_click=mostrar_habitos_fixos),
            ft.Button("✅ Tarefas", icon=ft.Icons.ASSIGNMENT_TURNED_IN_OUTLINED, on_click=mostrar_tarefas),
            ft.Button("⚡ Extras/Imprevistos", icon=ft.Icons.EVENT_AVAILABLE, on_click=mostrar_extras),
        ],
    )

    aba_rotina = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=16,
            expand=True,
            controls=[
                ft.Text("Rotina & Hábitos", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                linha_seletor_rotina,
                conteudo_rotina,
            ],
        ),
    )

    # ===================================================================
    # ABA: VEÍCULOS (manutenção, consumo e abastecimentos)
    # ===================================================================

    estado_veiculos = {"veiculo_id_ativo": None, "sub_secao": "plano"}

    CORES_STATUS_MANUTENCAO = {
        db.STATUS_MANUTENCAO_EM_DIA: ft.Colors.GREEN_300,
        db.STATUS_MANUTENCAO_ATENCAO: ft.Colors.AMBER_300,
        db.STATUS_MANUTENCAO_VENCIDO: ft.Colors.RED_300,
    }

    CORES_CRITICIDADE = {
        db.CRITICIDADE_ALTA: ft.Colors.RED_300,
        db.CRITICIDADE_MEDIA: ft.Colors.AMBER_300,
        db.CRITICIDADE_BAIXA: ft.Colors.GREY_400,
    }

    def formatar_valor_veiculos(v: float) -> str:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def formatar_data_br_veiculos(data_iso: Optional[str]) -> str:
        if not data_iso:
            return ""
        try:
            return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            return data_iso

    def _criar_card_veiculo_resumo(titulo: str, icone: str, cor: str, controle_valor: ft.Text) -> ft.Container:
        return ft.Container(
            expand=True,
            padding=18,
            border_radius=14,
            bgcolor=ft.Colors.GREY_900,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            content=ft.Column(
                spacing=6,
                controls=[
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Icon(icone, color=cor, size=18),
                            ft.Text(titulo, color=ft.Colors.GREY_400, size=12),
                        ],
                    ),
                    controle_valor,
                ],
            ),
        )

    # --- Diálogo: Novo Veículo -------------------------------------------------

    campo_apelido_veiculo = ft.TextField(label="Apelido", hint_text='ex: "Honda City"', autofocus=True)
    dropdown_tipo_veiculo = ft.Dropdown(
        label="Tipo",
        value=db.TIPO_VEICULO_CARRO,
        options=[
            ft.dropdown.Option(key=db.TIPO_VEICULO_CARRO, text="Carro"),
            ft.dropdown.Option(key=db.TIPO_VEICULO_MOTO, text="Moto"),
        ],
    )
    campo_marca_veiculo = ft.TextField(label="Marca")
    campo_modelo_veiculo = ft.TextField(label="Modelo")
    campo_ano_veiculo = ft.TextField(
        label="Ano", keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
    )
    campo_km_inicial_veiculo = ft.TextField(
        label="Km atual", keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
    )

    def fechar_dialogo_novo_veiculo(e: ft.ControlEvent = None) -> None:
        dialogo_novo_veiculo.open = False
        page.update()

    def abrir_dialogo_novo_veiculo(e: ft.ControlEvent = None) -> None:
        campo_apelido_veiculo.value = ""
        dropdown_tipo_veiculo.value = db.TIPO_VEICULO_CARRO
        campo_marca_veiculo.value = ""
        campo_modelo_veiculo.value = ""
        campo_ano_veiculo.value = ""
        campo_km_inicial_veiculo.value = ""
        dialogo_novo_veiculo.open = True
        page.update()

    def salvar_novo_veiculo(e: ft.ControlEvent) -> None:
        try:
            ano = int(campo_ano_veiculo.value) if (campo_ano_veiculo.value or "").strip() else None
            km_inicial = int((campo_km_inicial_veiculo.value or "0").strip())
        except ValueError:
            notificar("Verifique os valores de ano/km informados.", erro=True)
            return

        try:
            db.criar_veiculo(
                apelido=campo_apelido_veiculo.value,
                tipo=dropdown_tipo_veiculo.value,
                marca=campo_marca_veiculo.value,
                modelo=campo_modelo_veiculo.value,
                ano=ano,
                km_atual=km_inicial,
            )
        except ValueError as ve:
            notificar(str(ve), erro=True)
            return

        fechar_dialogo_novo_veiculo()
        notificar("Veículo cadastrado! Já pré-preenchi o plano de manutenção típico dele.")
        construir_lista_veiculos()

    dialogo_novo_veiculo = ft.AlertDialog(
        modal=True,
        title=ft.Text("Novo Veículo"),
        content=ft.Column(
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=380,
            controls=[
                campo_apelido_veiculo,
                dropdown_tipo_veiculo,
                campo_marca_veiculo,
                campo_modelo_veiculo,
                campo_ano_veiculo,
                campo_km_inicial_veiculo,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_novo_veiculo),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_novo_veiculo),
        ],
    )

    # --- Tela: Lista de Veículos -------------------------------------------------

    grade_veiculos = ft.Row(spacing=16, wrap=True)

    def construir_lista_veiculos() -> None:
        grade_veiculos.controls.clear()
        veiculos = db.listar_veiculos()

        if not veiculos:
            grade_veiculos.controls.append(
                ft.Text("Nenhum veículo cadastrado ainda.", italic=True, color=ft.Colors.GREY_500)
            )
            page.update()
            return

        for veiculo in veiculos:
            resumo = db.calcular_resumo_veiculo(veiculo["id"])
            icone_tipo = ft.Icons.DIRECTIONS_CAR if veiculo["tipo"] == db.TIPO_VEICULO_CARRO else ft.Icons.TWO_WHEELER

            alertas = []
            if resumo["qtd_vencidos"] > 0:
                alertas.append(
                    ft.Text(f"⚠️ {resumo['qtd_vencidos']} vencida(s)", size=12, color=ft.Colors.RED_300)
                )
            if resumo["qtd_atencao"] > 0:
                alertas.append(
                    ft.Text(f"🔶 {resumo['qtd_atencao']} próxima(s)", size=12, color=ft.Colors.AMBER_300)
                )
            if not alertas:
                alertas.append(ft.Text("✅ Tudo em dia", size=12, color=ft.Colors.GREEN_300))

            grade_veiculos.controls.append(
                ft.Container(
                    width=260,
                    padding=18,
                    border_radius=14,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    on_click=lambda e, vid=veiculo["id"]: abrir_detalhe_veiculo(vid),
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                spacing=8,
                                controls=[
                                    ft.Icon(icone_tipo, color=ft.Colors.BLUE_300),
                                    ft.Text(veiculo["apelido"], weight=ft.FontWeight.BOLD, size=16),
                                ],
                            ),
                            ft.Text(
                                f"{veiculo['marca']} {veiculo['modelo']} {veiculo['ano'] or ''}".strip(),
                                size=12, color=ft.Colors.GREY_400,
                            ),
                            ft.Text(f"{veiculo['km_atual']:,} km".replace(",", "."), size=14),
                            ft.Row(controls=alertas, wrap=True),
                        ],
                    ),
                )
            )

        page.update()

    tela_lista_veiculos = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Novo Veículo",
                        icon=ft.Icons.ADD,
                        bgcolor=ft.Colors.BLUE_600,
                        color=ft.Colors.WHITE,
                        on_click=abrir_dialogo_novo_veiculo,
                    ),
                ],
            ),
            ft.Container(expand=True, content=ft.Column(scroll=ft.ScrollMode.AUTO, controls=[grade_veiculos])),
        ],
    )

    # --- Diálogo: Atualizar Km ------------------------------------------------

    campo_novo_km_veiculo = ft.TextField(
        label="Novo km", keyboard_type=ft.KeyboardType.NUMBER, input_filter=ft.NumbersOnlyInputFilter(),
    )

    def fechar_dialogo_km_veiculo(e: ft.ControlEvent = None) -> None:
        dialogo_km_veiculo.open = False
        page.update()

    def abrir_dialogo_km_veiculo(e: ft.ControlEvent = None) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        veiculo = db.obter_veiculo(veiculo_id)
        campo_novo_km_veiculo.value = str(veiculo["km_atual"]) if veiculo else ""
        dialogo_km_veiculo.open = True
        page.update()

    def salvar_novo_km_veiculo(e: ft.ControlEvent) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        try:
            novo_km = int((campo_novo_km_veiculo.value or "").strip())
            db.atualizar_km_veiculo(veiculo_id, novo_km)
        except ValueError as ve:
            notificar(str(ve) or "Informe um km válido.", erro=True)
            return

        fechar_dialogo_km_veiculo()
        notificar("Quilometragem atualizada!")
        atualizar_detalhe_veiculo()

    dialogo_km_veiculo = ft.AlertDialog(
        modal=True,
        title=ft.Text("Atualizar Quilometragem"),
        content=ft.Column(tight=True, controls=[campo_novo_km_veiculo]),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_km_veiculo),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_novo_km_veiculo),
        ],
    )

    # --- Diálogo: Excluir Veículo (confirmação) ---------------------------------

    texto_confirmacao_exclusao_veiculo = ft.Text("")

    def fechar_dialogo_excluir_veiculo(e: ft.ControlEvent = None) -> None:
        dialogo_confirmar_exclusao_veiculo.open = False
        page.update()

    def abrir_dialogo_excluir_veiculo(e: ft.ControlEvent = None) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        veiculo = db.obter_veiculo(veiculo_id)
        nome = veiculo["apelido"] if veiculo else "este veículo"
        texto_confirmacao_exclusao_veiculo.value = (
            f'Tem certeza que deseja excluir "{nome}"? Isso apaga TODO o plano de '
            "manutenção, histórico e abastecimentos desse veículo. Essa ação não "
            "pode ser desfeita."
        )
        dialogo_confirmar_exclusao_veiculo.open = True
        page.update()

    def confirmar_exclusao_veiculo(e: ft.ControlEvent) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        try:
            db.deletar_veiculo(veiculo_id)
        except ValueError as ve:
            notificar(str(ve), erro=True)
        fechar_dialogo_excluir_veiculo()
        notificar("Veículo excluído.")
        voltar_lista_veiculos()

    dialogo_confirmar_exclusao_veiculo = ft.AlertDialog(
        modal=True,
        title=ft.Text("Excluir Veículo"),
        content=texto_confirmacao_exclusao_veiculo,
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_excluir_veiculo),
            ft.Button(
                "Excluir", icon=ft.Icons.DELETE_OUTLINE, bgcolor=ft.Colors.RED_700,
                color=ft.Colors.WHITE, on_click=confirmar_exclusao_veiculo,
            ),
        ],
    )

    # --- Sub-seção: Plano de Manutenção ------------------------------------------

    lista_plano_manutencao_view = ft.ListView(expand=True, spacing=8, padding=10)

    campo_nome_item_manutencao = ft.TextField(label="Nome do item", hint_text='ex: "Troca de óleo"')
    campo_intervalo_km_item = ft.TextField(
        label="Intervalo por km (opcional)", keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    campo_intervalo_dias_item = ft.TextField(
        label="Intervalo por dias (opcional)", keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    dropdown_criticidade_item = ft.Dropdown(
        label="Criticidade",
        value=db.CRITICIDADE_MEDIA,
        options=[
            ft.dropdown.Option(key=db.CRITICIDADE_ALTA, text="Alta"),
            ft.dropdown.Option(key=db.CRITICIDADE_MEDIA, text="Média"),
            ft.dropdown.Option(key=db.CRITICIDADE_BAIXA, text="Baixa"),
        ],
    )

    def fechar_dialogo_novo_item(e: ft.ControlEvent = None) -> None:
        dialogo_novo_item.open = False
        page.update()

    def abrir_dialogo_novo_item(e: ft.ControlEvent = None) -> None:
        campo_nome_item_manutencao.value = ""
        campo_intervalo_km_item.value = ""
        campo_intervalo_dias_item.value = ""
        dropdown_criticidade_item.value = db.CRITICIDADE_MEDIA
        dialogo_novo_item.open = True
        page.update()

    def salvar_novo_item(e: ft.ControlEvent) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        try:
            intervalo_km = int(campo_intervalo_km_item.value) if (campo_intervalo_km_item.value or "").strip() else None
            intervalo_dias = int(campo_intervalo_dias_item.value) if (campo_intervalo_dias_item.value or "").strip() else None
            db.adicionar_item_manutencao(
                veiculo_id, campo_nome_item_manutencao.value, intervalo_km, intervalo_dias,
                dropdown_criticidade_item.value,
            )
        except ValueError as ve:
            notificar(str(ve) or "Verifique os valores informados.", erro=True)
            return

        fechar_dialogo_novo_item()
        notificar("Item de manutenção adicionado!")
        atualizar_detalhe_veiculo()

    dialogo_novo_item = ft.AlertDialog(
        modal=True,
        title=ft.Text("Novo Item de Manutenção"),
        content=ft.Column(
            tight=True,
            controls=[
                campo_nome_item_manutencao, campo_intervalo_km_item,
                campo_intervalo_dias_item, dropdown_criticidade_item,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_novo_item),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_novo_item),
        ],
    )

    def excluir_item_manutencao_ui(item_id: int) -> None:
        db.deletar_item_manutencao(item_id)
        notificar("Item removido do plano.")
        atualizar_detalhe_veiculo()

    # --- Diálogo: Registrar Manutenção (troca de item OU avulsa) ----------------

    estado_registro_manutencao = {"item_id": None}

    campo_descricao_manutencao = ft.TextField(label="Descrição")
    campo_data_manutencao = ft.TextField(label="Data", hint_text="DD/MM/AAAA")
    campo_km_manutencao = ft.TextField(
        label="Km no momento (opcional)", keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    campo_custo_manutencao = ft.TextField(label="Custo (opcional)")
    campo_local_manutencao = ft.TextField(label="Oficina/Local (opcional)")

    def fechar_dialogo_registrar_manutencao(e: ft.ControlEvent = None) -> None:
        dialogo_registrar_manutencao.open = False
        page.update()

    def abrir_dialogo_registrar_manutencao(item_id: Optional[int] = None, descricao_sugerida: str = "") -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        veiculo = db.obter_veiculo(veiculo_id)
        estado_registro_manutencao["item_id"] = item_id
        campo_descricao_manutencao.value = descricao_sugerida
        campo_data_manutencao.value = datetime.now().strftime("%d/%m/%Y")
        campo_km_manutencao.value = str(veiculo["km_atual"]) if veiculo else ""
        campo_custo_manutencao.value = ""
        campo_local_manutencao.value = ""
        dialogo_registrar_manutencao.open = True
        page.update()

    def salvar_manutencao_realizada(e: ft.ControlEvent) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]

        try:
            data_iso = datetime.strptime(
                (campo_data_manutencao.value or "").strip(), "%d/%m/%Y",
            ).strftime("%Y-%m-%d")
        except ValueError:
            notificar("Data inválida. Utilize DD/MM/AAAA.", erro=True)
            return

        km = None
        if (campo_km_manutencao.value or "").strip():
            try:
                km = int(campo_km_manutencao.value.strip())
            except ValueError:
                notificar("Km inválido.", erro=True)
                return

        custo = None
        if (campo_custo_manutencao.value or "").strip():
            try:
                custo = float(campo_custo_manutencao.value.replace(",", "."))
            except ValueError:
                notificar("Custo inválido.", erro=True)
                return

        try:
            db.registrar_manutencao_realizada(
                veiculo_id=veiculo_id,
                descricao=campo_descricao_manutencao.value,
                data=data_iso,
                km=km,
                custo=custo,
                local=campo_local_manutencao.value,
                item_id=estado_registro_manutencao["item_id"],
            )
        except ValueError as ve:
            notificar(str(ve), erro=True)
            return

        fechar_dialogo_registrar_manutencao()
        notificar("Manutenção registrada!")
        atualizar_detalhe_veiculo()

    dialogo_registrar_manutencao = ft.AlertDialog(
        modal=True,
        title=ft.Text("Registrar Manutenção"),
        content=ft.Column(
            tight=True,
            scroll=ft.ScrollMode.AUTO,
            height=340,
            controls=[
                campo_descricao_manutencao, campo_data_manutencao, campo_km_manutencao,
                campo_custo_manutencao, campo_local_manutencao,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_registrar_manutencao),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_manutencao_realizada),
        ],
    )

    def construir_lista_plano_manutencao() -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        lista_plano_manutencao_view.controls.clear()

        itens = db.listar_itens_manutencao(veiculo_id) if veiculo_id else []

        if not itens:
            lista_plano_manutencao_view.controls.append(
                ft.Text("Nenhum item cadastrado no plano.", italic=True, color=ft.Colors.GREY_500)
            )
            return

        for item in itens:
            cor_status = CORES_STATUS_MANUTENCAO.get(item["status"], ft.Colors.GREY_400)
            cor_criticidade = CORES_CRITICIDADE.get(item["criticidade"], ft.Colors.GREY_400)

            partes_intervalo = []
            if item["intervalo_km"]:
                partes_intervalo.append(f"a cada {item['intervalo_km']:,} km".replace(",", "."))
            if item["intervalo_dias"]:
                partes_intervalo.append(f"a cada {item['intervalo_dias']} dias")

            partes_restante = []
            if item["km_restante"] is not None:
                partes_restante.append(f"{item['km_restante']:,} km restantes".replace(",", "."))
            if item["dias_restantes"] is not None:
                partes_restante.append(f"{item['dias_restantes']} dias restantes")

            lista_plano_manutencao_view.controls.append(
                ft.Container(
                    padding=14,
                    border_radius=12,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    content=ft.Row(
                        controls=[
                            ft.Container(width=4, height=40, bgcolor=cor_status, border_radius=2),
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Row(
                                        spacing=8,
                                        controls=[
                                            ft.Text(item["nome_item"], size=14, weight=ft.FontWeight.W_600),
                                            ft.Container(
                                                content=ft.Text(item["criticidade"], size=10, color=ft.Colors.GREY_900),
                                                bgcolor=cor_criticidade,
                                                padding=ft.Padding.symmetric(horizontal=6, vertical=1),
                                                border_radius=10,
                                            ),
                                        ],
                                    ),
                                    ft.Text(" • ".join(partes_intervalo), size=11, color=ft.Colors.GREY_400),
                                    ft.Text(
                                        " • ".join(partes_restante) + f" — {item['status']}",
                                        size=11, color=cor_status,
                                    ),
                                ],
                            ),
                            ft.Button(
                                "Registrar Troca",
                                icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                                on_click=lambda e, iid=item["id"], nome=item["nome_item"]: (
                                    abrir_dialogo_registrar_manutencao(iid, nome)
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=ft.Colors.RED_300,
                                icon_size=18,
                                tooltip="Remover item do plano",
                                on_click=lambda e, iid=item["id"]: excluir_item_manutencao_ui(iid),
                            ),
                        ],
                    ),
                )
            )

    tela_plano_manutencao = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button("Novo Item", icon=ft.Icons.ADD, on_click=abrir_dialogo_novo_item),
                ],
            ),
            ft.Container(
                expand=True, border=ft.Border.all(1, ft.Colors.GREY_800), border_radius=10,
                padding=10, content=lista_plano_manutencao_view,
            ),
        ],
    )

    # --- Sub-seção: Histórico de Manutenções ------------------------------------

    lista_historico_manutencao_view = ft.ListView(expand=True, spacing=8, padding=10)

    def construir_lista_historico_manutencao() -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        lista_historico_manutencao_view.controls.clear()

        registros = db.listar_manutencoes_realizadas(veiculo_id) if veiculo_id else []

        if not registros:
            lista_historico_manutencao_view.controls.append(
                ft.Text("Nenhuma manutenção registrada ainda.", italic=True, color=ft.Colors.GREY_500)
            )
            return

        for registro in registros:
            detalhes = [formatar_data_br_veiculos(registro["data"])]
            if registro["km"] is not None:
                detalhes.append(f"{registro['km']:,} km".replace(",", "."))
            if registro["local"]:
                detalhes.append(registro["local"])

            lista_historico_manutencao_view.controls.append(
                ft.Container(
                    padding=14,
                    border_radius=12,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(registro["descricao"], size=14, weight=ft.FontWeight.W_600),
                                    ft.Text(" • ".join(detalhes), size=11, color=ft.Colors.GREY_400),
                                ],
                            ),
                            ft.Text(
                                formatar_valor_veiculos(registro["custo"]) if registro["custo"] else "",
                                size=13, color=ft.Colors.AMBER_300,
                            ),
                        ],
                    ),
                )
            )

    tela_historico_manutencao = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Nova Manutenção Avulsa",
                        icon=ft.Icons.ADD,
                        on_click=lambda e: abrir_dialogo_registrar_manutencao(None, ""),
                    ),
                ],
            ),
            ft.Container(
                expand=True, border=ft.Border.all(1, ft.Colors.GREY_800), border_radius=10,
                padding=10, content=lista_historico_manutencao_view,
            ),
        ],
    )

    # --- Sub-seção: Abastecimentos ----------------------------------------------

    lista_abastecimentos_view = ft.ListView(expand=True, spacing=8, padding=10)

    campo_data_abastecimento = ft.TextField(label="Data", hint_text="DD/MM/AAAA")
    campo_km_abastecimento = ft.TextField(
        label="Km no abastecimento", keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
    )
    campo_litros_abastecimento = ft.TextField(label="Litros")
    campo_valor_abastecimento = ft.TextField(label="Valor total (R$)")
    dropdown_combustivel_abastecimento = ft.Dropdown(
        label="Combustível",
        value="Gasolina",
        options=[
            ft.dropdown.Option(key="Gasolina", text="Gasolina"),
            ft.dropdown.Option(key="Etanol", text="Etanol"),
            ft.dropdown.Option(key="Diesel", text="Diesel"),
        ],
    )

    def fechar_dialogo_abastecimento(e: ft.ControlEvent = None) -> None:
        dialogo_abastecimento.open = False
        page.update()

    def abrir_dialogo_abastecimento(e: ft.ControlEvent = None) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        veiculo = db.obter_veiculo(veiculo_id)
        campo_data_abastecimento.value = datetime.now().strftime("%d/%m/%Y")
        campo_km_abastecimento.value = str(veiculo["km_atual"]) if veiculo else ""
        campo_litros_abastecimento.value = ""
        campo_valor_abastecimento.value = ""
        dropdown_combustivel_abastecimento.value = "Gasolina"
        dialogo_abastecimento.open = True
        page.update()

    def salvar_abastecimento(e: ft.ControlEvent) -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]

        try:
            data_iso = datetime.strptime(
                (campo_data_abastecimento.value or "").strip(), "%d/%m/%Y",
            ).strftime("%Y-%m-%d")
            km = int(campo_km_abastecimento.value.strip())
            litros = float(campo_litros_abastecimento.value.replace(",", "."))
            valor_total = float(campo_valor_abastecimento.value.replace(",", "."))
        except ValueError:
            notificar("Verifique os valores informados (data, km, litros, valor).", erro=True)
            return

        try:
            db.adicionar_abastecimento(
                veiculo_id, data_iso, km, litros, valor_total, dropdown_combustivel_abastecimento.value,
            )
        except ValueError as ve:
            notificar(str(ve), erro=True)
            return

        fechar_dialogo_abastecimento()
        notificar("Abastecimento registrado!")
        atualizar_detalhe_veiculo()

    dialogo_abastecimento = ft.AlertDialog(
        modal=True,
        title=ft.Text("Novo Abastecimento"),
        content=ft.Column(
            tight=True,
            controls=[
                campo_data_abastecimento, campo_km_abastecimento, campo_litros_abastecimento,
                campo_valor_abastecimento, dropdown_combustivel_abastecimento,
            ],
        ),
        actions=[
            ft.Button("Cancelar", on_click=fechar_dialogo_abastecimento),
            ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_abastecimento),
        ],
    )

    def construir_lista_abastecimentos() -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        lista_abastecimentos_view.controls.clear()

        abastecimentos = db.listar_abastecimentos_com_consumo(veiculo_id) if veiculo_id else []

        if not abastecimentos:
            lista_abastecimentos_view.controls.append(
                ft.Text("Nenhum abastecimento registrado ainda.", italic=True, color=ft.Colors.GREY_500)
            )
            return

        for abastecimento in abastecimentos:
            consumo_texto = (
                f"{abastecimento['consumo_km_l']:.2f} km/L".replace(".", ",")
                if abastecimento["consumo_km_l"] is not None
                else "—"
            )

            lista_abastecimentos_view.controls.append(
                ft.Container(
                    padding=14,
                    border_radius=12,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Column(
                                expand=True,
                                spacing=2,
                                controls=[
                                    ft.Text(
                                        f"{formatar_data_br_veiculos(abastecimento['data'])} — "
                                        f"{abastecimento['km']:,} km".replace(",", "."),
                                        size=14, weight=ft.FontWeight.W_600,
                                    ),
                                    ft.Text(
                                        f"{abastecimento['litros']:.1f} L • {abastecimento['combustivel']} • "
                                        f"{formatar_valor_veiculos(abastecimento['valor_total'])}",
                                        size=11, color=ft.Colors.GREY_400,
                                    ),
                                ],
                            ),
                            ft.Text(consumo_texto, size=14, color=ft.Colors.GREEN_300, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                )
            )

    tela_abastecimentos = ft.Column(
        expand=True,
        spacing=15,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Button(
                        "Novo Abastecimento", icon=ft.Icons.ADD,
                        bgcolor=ft.Colors.BLUE_600, color=ft.Colors.WHITE,
                        on_click=abrir_dialogo_abastecimento,
                    ),
                ],
            ),
            ft.Container(
                expand=True, border=ft.Border.all(1, ft.Colors.GREY_800), border_radius=10,
                padding=10, content=lista_abastecimentos_view,
            ),
        ],
    )

    # --- Tela: Detalhe do Veículo (cabeçalho + seletor de sub-seções) -----------

    texto_titulo_detalhe_veiculo = ft.Text("", size=22, weight=ft.FontWeight.BOLD)
    texto_subtitulo_detalhe_veiculo = ft.Text("", size=13, color=ft.Colors.GREY_400)
    texto_km_atual_veiculo = ft.Text("", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300)
    texto_gasto_manutencao_veiculo = ft.Text("", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)
    texto_gasto_combustivel_veiculo = ft.Text("", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300)
    texto_consumo_medio_veiculo = ft.Text("", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_300)

    linha_cards_detalhe_veiculo = ft.Row(
        spacing=16,
        controls=[
            _criar_card_veiculo_resumo("Km Atual", ft.Icons.SPEED, ft.Colors.BLUE_300, texto_km_atual_veiculo),
            _criar_card_veiculo_resumo(
                "Gasto em Manutenção", ft.Icons.BUILD, ft.Colors.AMBER_300, texto_gasto_manutencao_veiculo,
            ),
            _criar_card_veiculo_resumo(
                "Gasto em Combustível", ft.Icons.LOCAL_GAS_STATION, ft.Colors.AMBER_300, texto_gasto_combustivel_veiculo,
            ),
            _criar_card_veiculo_resumo(
                "Consumo Médio", ft.Icons.TRENDING_UP, ft.Colors.GREEN_300, texto_consumo_medio_veiculo,
            ),
        ],
    )

    conteudo_sub_secao_veiculo = ft.Container(expand=True, content=tela_plano_manutencao)

    def mostrar_sub_secao_plano(e: ft.ControlEvent = None) -> None:
        estado_veiculos["sub_secao"] = "plano"
        construir_lista_plano_manutencao()
        conteudo_sub_secao_veiculo.content = tela_plano_manutencao
        page.update()

    def mostrar_sub_secao_historico(e: ft.ControlEvent = None) -> None:
        estado_veiculos["sub_secao"] = "historico"
        construir_lista_historico_manutencao()
        conteudo_sub_secao_veiculo.content = tela_historico_manutencao
        page.update()

    def mostrar_sub_secao_abastecimentos(e: ft.ControlEvent = None) -> None:
        estado_veiculos["sub_secao"] = "abastecimentos"
        construir_lista_abastecimentos()
        conteudo_sub_secao_veiculo.content = tela_abastecimentos
        page.update()

    linha_seletor_detalhe_veiculo = ft.Row(
        spacing=12,
        controls=[
            ft.Button("🔧 Plano de Manutenção", on_click=mostrar_sub_secao_plano),
            ft.Button("📋 Histórico", on_click=mostrar_sub_secao_historico),
            ft.Button("⛽ Abastecimentos", on_click=mostrar_sub_secao_abastecimentos),
        ],
    )

    def voltar_lista_veiculos(e: ft.ControlEvent = None) -> None:
        estado_veiculos["veiculo_id_ativo"] = None
        construir_lista_veiculos()
        conteudo_veiculos.content = tela_lista_veiculos
        page.update()

    tela_detalhe_veiculo = ft.Column(
        expand=True,
        spacing=16,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    ft.Row(
                        spacing=10,
                        controls=[
                            ft.IconButton(icon=ft.Icons.ARROW_BACK, on_click=voltar_lista_veiculos),
                            ft.Column(
                                spacing=0,
                                controls=[texto_titulo_detalhe_veiculo, texto_subtitulo_detalhe_veiculo],
                            ),
                        ],
                    ),
                    ft.Row(
                        spacing=8,
                        controls=[
                            ft.Button(
                                "Atualizar Km", icon=ft.Icons.SPEED, on_click=abrir_dialogo_km_veiculo,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_300,
                                tooltip="Excluir veículo", on_click=abrir_dialogo_excluir_veiculo,
                            ),
                        ],
                    ),
                ],
            ),
            linha_cards_detalhe_veiculo,
            linha_seletor_detalhe_veiculo,
            conteudo_sub_secao_veiculo,
        ],
    )

    def atualizar_detalhe_veiculo() -> None:
        veiculo_id = estado_veiculos["veiculo_id_ativo"]
        if not veiculo_id:
            return

        veiculo = db.obter_veiculo(veiculo_id)
        if veiculo is None:
            voltar_lista_veiculos()
            return

        texto_titulo_detalhe_veiculo.value = veiculo["apelido"]
        texto_subtitulo_detalhe_veiculo.value = (
            f"{veiculo['marca']} {veiculo['modelo']} {veiculo['ano'] or ''}".strip()
        )
        texto_km_atual_veiculo.value = f"{veiculo['km_atual']:,} km".replace(",", ".")

        resumo = db.calcular_resumo_veiculo(veiculo_id)
        texto_gasto_manutencao_veiculo.value = formatar_valor_veiculos(resumo["gasto_manutencao"])
        texto_gasto_combustivel_veiculo.value = formatar_valor_veiculos(resumo["gasto_combustivel"])
        texto_consumo_medio_veiculo.value = (
            f"{resumo['consumo_medio_km_l']:.2f} km/L".replace(".", ",")
            if resumo["consumo_medio_km_l"] is not None
            else "—"
        )

        sub_secao = estado_veiculos["sub_secao"]
        if sub_secao == "plano":
            construir_lista_plano_manutencao()
        elif sub_secao == "historico":
            construir_lista_historico_manutencao()
        else:
            construir_lista_abastecimentos()

        page.update()

    def abrir_detalhe_veiculo(veiculo_id: int) -> None:
        estado_veiculos["veiculo_id_ativo"] = veiculo_id
        estado_veiculos["sub_secao"] = "plano"
        conteudo_sub_secao_veiculo.content = tela_plano_manutencao
        atualizar_detalhe_veiculo()
        conteudo_veiculos.content = tela_detalhe_veiculo
        page.update()

    # --- Montagem final da aba ---------------------------------------------------

    conteudo_veiculos = ft.Container(expand=True, content=tela_lista_veiculos)

    aba_veiculos = ft.Container(
        padding=30,
        content=ft.Column(
            spacing=16,
            expand=True,
            controls=[
                ft.Text("Veículos", size=24, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                conteudo_veiculos,
            ],
        ),
    )

    # ===================================================================
    # ABA: FINANCEIRO (controle de boletos mensais)
    # ===================================================================

    def _gerar_opcoes_mes(intervalo: int = 6) -> list:
        """
        Gera uma lista de strings 'YYYY-MM' cobrindo `intervalo` meses antes
        e `intervalo` meses depois do mês atual, para popular o Dropdown de
        filtro (sem depender de bibliotecas externas de data).
        """
        agora = datetime.now()
        opcoes = []
        for delta in range(-intervalo, intervalo + 1):
            mes_total = (agora.month - 1) + delta
            ano = agora.year + mes_total // 12
            mes = mes_total % 12 + 1
            opcoes.append(f"{ano:04d}-{mes:02d}")
        return opcoes

    NOMES_MESES = {
        "01": "Janeiro", "02": "Fevereiro", "03": "Março", "04": "Abril",
        "05": "Maio", "06": "Junho", "07": "Julho", "08": "Agosto",
        "09": "Setembro", "10": "Outubro", "11": "Novembro", "12": "Dezembro",
    }

    def _rotulo_mes(ano_mes: str) -> str:
        ano, mes = ano_mes.split("-")
        return f"{NOMES_MESES.get(mes, mes)}/{ano}"

    def construir_tela_financeiro() -> ft.Container:
        """
        Monta a aba 'Financeiro': cards de resumo, filtro de mês/ano,
        formulário de cadastro (AlertDialog) e a lista dinâmica de boletos.
        """
        mes_atual_str = datetime.now().strftime("%Y-%m")
        clipboard = ft.Clipboard()  # Service headless — não vai para page.overlay.

        # --- Cards de resumo -------------------------------------------------
        texto_total_entradas = ft.Text(
            "R$ 0,00",
            size=26,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.GREEN_400,
        )

        texto_total_saidas = ft.Text(
            "R$ 0,00",
            size=26,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.RED_300,
        )

        texto_balanco = ft.Text(
            "R$ 0,00",
            size=26,
            weight=ft.FontWeight.BOLD,
        )

        texto_total_poupado = ft.Text(
            "R$ 0,00",
            size=26,
            weight=ft.FontWeight.BOLD,
            color=ft.Colors.BLUE_300,
        )

        def _criar_card_financeiro(titulo: str, icone: str, cor: str, controle_valor: ft.Text) -> ft.Container:
            return ft.Container(
                expand=True,
                padding=20,
                border_radius=16,
                bgcolor=ft.Colors.GREY_900,
                border=ft.Border.all(1, ft.Colors.GREY_800),
                content=ft.Column(
                    spacing=6,
                    controls=[
                        ft.Row(
                            spacing=8,
                            controls=[
                                ft.Icon(icone, color=cor, size=20),
                                ft.Text(titulo, color=ft.Colors.GREY_400, size=13),
                            ],
                        ),
                        controle_valor,
                    ],
                ),
            )

        linha_cards = ft.Row(
            spacing=16,
            controls=[
    _criar_card_financeiro(
        "Total Entradas",
        ft.Icons.TRENDING_UP,
        ft.Colors.GREEN_400,
        texto_total_entradas,
    ),

    _criar_card_financeiro(
        "Total Saídas",
        ft.Icons.TRENDING_DOWN,
        ft.Colors.RED_300,
        texto_total_saidas,
    ),

    _criar_card_financeiro(
        "Balanço Líquido",
        ft.Icons.ACCOUNT_BALANCE_WALLET,
        ft.Colors.AMBER_300,
        texto_balanco,
    ),

    _criar_card_financeiro(
        "Total Poupado",
        ft.Icons.SAVINGS,
        ft.Colors.BLUE_300,
        texto_total_poupado,
    ),
],
        )

        # --- Filtro de mês/ano -------------------------------------------------
        dropdown_mes_financeiro = ft.Dropdown(
            label="Mês/Ano",
            width=220,
            value=mes_atual_str,
            options=[ft.dropdown.Option(key=m, text=_rotulo_mes(m)) for m in _gerar_opcoes_mes()],
        )

        # --- Lista de boletos ----------------------------------------------
        lista_boletos_view = ft.ListView(expand=True, spacing=10, padding=10)

        def formatar_valor(v: float) -> str:
            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def formatar_data_br(data_iso: str) -> str:
            try:
                return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
            except ValueError:
                return data_iso

        async def copiar_codigo_barras(codigo: str) -> None:
            if not codigo:
                notificar("Este boleto não tem código de barras cadastrado.", erro=True)
                return
            await clipboard.set(codigo)
            notificar("Código de barras copiado para a área de transferência!")

        def alternar_status_boleto_ui(boleto_id: int, status_atual: str) -> None:
            novo_status = (
                db.STATUS_BOLETO_PENDENTE if status_atual == db.STATUS_BOLETO_PAGO else db.STATUS_BOLETO_PAGO
            )
            db.alterar_status_boleto(boleto_id, novo_status)
            notificar(f"Boleto marcado como '{novo_status}'.")
            atualizar_tela_financeiro()

        def excluir_boleto_ui(boleto_id: int) -> None:
            db.deletar_boleto(boleto_id)
            notificar("Boleto removido.")
            atualizar_tela_financeiro()

        def excluir_transacao_ui(transacao_id: int):

            db.deletar_transacao(transacao_id)

            notificar("Transação removida.")

            atualizar_tela_financeiro()

        def atualizar_tela_financeiro(e: ft.ControlEvent = None) -> None:
            ano_mes = dropdown_mes_financeiro.value or mes_atual_str
            boletos = db.listar_boletos_mes(ano_mes)
            transacoes = db.listar_transacoes_mes(ano_mes)
            metas = db.listar_metas()
            hoje = datetime.now().date()

            total_entradas = sum(
                    t["valor"]
                    for t in transacoes
                    if t["tipo"] == "Receita"
                )

            total_despesas_variaveis = sum(
                    t["valor"]
                    for t in transacoes
                    if t["tipo"] == "Despesa_Variavel"
                )

            total_boletos = sum(
                    b["valor"]
                    for b in boletos
                )

            total_saidas = total_boletos + total_despesas_variaveis

            balanco = total_entradas - total_saidas

            total_poupado = sum(
                    meta["valor_atual"]
                    for meta in metas
)

            texto_total_entradas.value = formatar_valor(total_entradas)
            texto_total_saidas.value = formatar_valor(total_saidas)
            texto_balanco.value = formatar_valor(balanco)
            texto_total_poupado.value = formatar_valor(total_poupado)

            if balanco >= 0:
                texto_balanco.color = ft.Colors.GREEN_400
            else:
                texto_balanco.color = ft.Colors.RED_300

            # --------------------------------------------------------------
            # Atualiza lista de transações
            # --------------------------------------------------------------

            lista_transacoes_view.controls.clear()

            if not transacoes:

                lista_transacoes_view.controls.append(
                    ft.Text(
                        "Nenhuma transação cadastrada.",
                        italic=True,
                        color=ft.Colors.GREY_500,
                    )
                )

            else:

                for t in transacoes:

                    receita = t["tipo"] == "Receita"

                    cor = (
                        ft.Colors.GREEN_400
                        if receita
                        else ft.Colors.RED_300
                    )

                    icone = (
                        ft.Icons.ARROW_UPWARD
                        if receita
                        else ft.Icons.ARROW_DOWNWARD
                    )

                    texto_tipo = (
                        "Receita"
                        if receita
                        else "Despesa"
                    )

                    card = ft.Container(
                        padding=16,
                        border_radius=14,
                        bgcolor=ft.Colors.GREY_900,
                        border=ft.Border.all(
                            1,
                            ft.Colors.GREY_800,
                        ),
                        content=ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[

                                ft.Column(
                                    expand=True,
                                    spacing=4,
                                    controls=[

                                        ft.Row(
                                            controls=[
                                                ft.Icon(
                                                    icone,
                                                    color=cor,
                                                ),
                                                ft.Text(
                                                    texto_tipo,
                                                    color=cor,
                                                    weight=ft.FontWeight.BOLD,
                                                ),
                                            ]
                                        ),

                                        ft.Text(
                                            t["descricao"],
                                            size=16,
                                            weight=ft.FontWeight.BOLD,
                                        ),

                                        ft.Text(
                                            f"Categoria: {t['categoria']}",
                                            color=ft.Colors.GREY_400,
                                        ),

                                        ft.Text(
                                            formatar_data_br(t["data"]),
                                            color=ft.Colors.GREY_400,
                                        ),

                                        ft.Text(
                                            formatar_valor(t["valor"]),
                                            size=15,
                                            weight=ft.FontWeight.BOLD,
                                            color=cor,
                                        ),

                                    ],
                                ),

                                ft.IconButton(
                                    icon=ft.Icons.DELETE_OUTLINE,
                                    icon_color=ft.Colors.RED_300,
                                    tooltip="Excluir",

                                    on_click=lambda e, tid=t["id"]: excluir_transacao_ui(tid),
                                ),

                            ],
                        ),
                    )

                    lista_transacoes_view.controls.append(card)

            lista_boletos_view.controls.clear()

            if not boletos:
                lista_boletos_view.controls.append(
                    ft.Text(
                        "Nenhum boleto cadastrado para este mês.",
                        italic=True,
                        color=ft.Colors.GREY_500,
                    )
                )
                page.update()
                return
            for b in boletos:
                try:
                    data_venc = datetime.strptime(b["data_vencimento"], "%Y-%m-%d").date()
                    dias_restantes = (data_venc - hoje).days
                except ValueError:
                    dias_restantes = None

                pago = b["status"] == db.STATUS_BOLETO_PAGO

                # Regra visual: Pago = verde sutil; vencido+Pendente = vermelho;
                # vence em até 3 dias + Pendente = amarelo; caso contrário = neutro.
                if pago:
                    cor_borda = ft.Colors.GREEN_700
                    cor_bg = ft.Colors.GREEN_900
                    texto_prazo = "Pago"
                    cor_texto_prazo = ft.Colors.GREEN_300
                elif dias_restantes is not None and dias_restantes < 0:
                    cor_borda = ft.Colors.RED_700
                    cor_bg = ft.Colors.RED_900
                    texto_prazo = f"Vencido há {abs(dias_restantes)} dia(s)"
                    cor_texto_prazo = ft.Colors.RED_300
                elif dias_restantes is not None and dias_restantes <= 3:
                    cor_borda = ft.Colors.AMBER_700
                    cor_bg = ft.Colors.AMBER_900
                    texto_prazo = "Vence hoje!" if dias_restantes == 0 else f"Vence em {dias_restantes} dia(s)"
                    cor_texto_prazo = ft.Colors.AMBER_300
                else:
                    cor_borda = ft.Colors.GREY_800
                    cor_bg = ft.Colors.GREY_900
                    texto_prazo = f"Vence em {dias_restantes} dia(s)" if dias_restantes is not None else ""
                    cor_texto_prazo = ft.Colors.GREY_400

                botoes_acao = [
                    ft.IconButton(
                        icon=ft.Icons.UNDO if pago else ft.Icons.CHECK_CIRCLE_OUTLINE,
                        tooltip="Estornar" if pago else "Marcar como Pago",
                        icon_color=ft.Colors.AMBER_300 if pago else ft.Colors.GREEN_300,
                        on_click=lambda e, bid=b["id"], st=b["status"]: alternar_status_boleto_ui(bid, st),
                    ),
                ]
                if b["codigo_barras"]:
                    botoes_acao.append(
                        ft.IconButton(
                            icon=ft.Icons.COPY,
                            tooltip="Copiar código de barras",
                            on_click=lambda e, cod=b["codigo_barras"]: copiar_codigo_barras(cod),
                        )
                    )
                botoes_acao.append(
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE,
                        icon_color=ft.Colors.RED_300,
                        tooltip="Excluir boleto",
                        on_click=lambda e, bid=b["id"]: excluir_boleto_ui(bid),
                    )
                )

                card_boleto = ft.Container(
                    padding=16,
                    border_radius=14,
                    bgcolor=cor_bg,
                    border=ft.Border.all(1, cor_borda),
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Column(
                                spacing=2,
                                expand=True,
                                controls=[
                                    ft.Text(b["nome"], weight=ft.FontWeight.W_600, size=15),
                                    ft.Text(
                                        f"Vencimento: {formatar_data_br(b['data_vencimento'])}   |   "
                                        f"{formatar_valor(b['valor'])}",
                                        size=12,
                                        color=ft.Colors.GREY_400,
                                    ),
                                    ft.Text(texto_prazo, size=12, color=cor_texto_prazo, weight=ft.FontWeight.BOLD),
                                ],
                            ),
                            ft.Row(spacing=0, controls=botoes_acao),
                        ],
                    ),
                )
                lista_boletos_view.controls.append(card_boleto)

            atualizar_lista_metas()

            page.update()

        dropdown_mes_financeiro.on_select = atualizar_tela_financeiro

        # --- Diálogo de cadastro de boleto ----------------------------------

        campo_nome_boleto = ft.TextField(label="Nome do Boleto", autofocus=True)
        campo_valor_boleto = ft.TextField(
            label="Valor (R$)",
            input_filter=ft.InputFilter(regex_string=r"[0-9.]", allow=True),
        )
        campo_vencimento_boleto = ft.TextField(
            label="Data de Vencimento", hint_text="DD/MM/AAAA"
        )
        campo_codigo_barras_boleto = ft.TextField(
            label="Código de Barras / Copia e Cola",
            multiline=True,
            min_lines=2,
            max_lines=4,
        )

        def fechar_dialogo_boleto(e: ft.ControlEvent = None) -> None:
            dialogo_boleto.open = False
            page.update()

        def abrir_dialogo_boleto(e: ft.ControlEvent = None) -> None:
            campo_nome_boleto.value = ""
            campo_valor_boleto.value = ""
            campo_vencimento_boleto.value = ""
            campo_codigo_barras_boleto.value = ""
            dialogo_boleto.open = True
            page.update()

        def salvar_boleto(e: ft.ControlEvent) -> None:
            nome = (campo_nome_boleto.value or "").strip()
            if not nome:
                notificar("Informe o nome do boleto.", erro=True)
                return

            try:
                valor = float((campo_valor_boleto.value or "0").strip().replace(",", ".") or 0)
            except ValueError:
                notificar("Valor inválido. Use apenas números (ex: 189.90).", erro=True)
                return

            try:
                data_venc = datetime.strptime(
                    (campo_vencimento_boleto.value or "").strip(), "%d/%m/%Y"
                )
            except ValueError:
                notificar("Data de vencimento inválida. Use o formato DD/MM/AAAA.", erro=True)
                return

            try:
                db.adicionar_boleto(
                    nome=nome,
                    valor=valor,
                    data_vencimento=data_venc.strftime("%Y-%m-%d"),
                    codigo_barras=campo_codigo_barras_boleto.value or "",
                )
            except ValueError as ve:
                notificar(str(ve), erro=True)
                return

            fechar_dialogo_boleto()
            notificar(f"Boleto '{nome}' cadastrado com sucesso!")

            # Se o boleto cadastrado cair no mês atualmente filtrado, atualiza
            # a lista na hora; senão, muda o filtro para o mês do boleto.
            mes_do_boleto = data_venc.strftime("%Y-%m")
            if dropdown_mes_financeiro.value != mes_do_boleto:
                dropdown_mes_financeiro.value = mes_do_boleto
            atualizar_tela_financeiro()

        dialogo_boleto = ft.AlertDialog(
            modal=True,
            title=ft.Text("Novo Boleto", weight=ft.FontWeight.BOLD),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    campo_nome_boleto,
                    campo_valor_boleto,
                    campo_vencimento_boleto,
                    campo_codigo_barras_boleto,
                ],
            ),
            actions=[
                ft.Button("Cancelar", on_click=fechar_dialogo_boleto),
                ft.Button(
                    "Salvar Boleto",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.GREEN_700,
                    color=ft.Colors.WHITE,
                    on_click=salvar_boleto,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialogos_financeiro_para_overlay.append(dialogo_boleto)

        botao_novo_boleto = ft.Button(
            "Novo Boleto",
            icon=ft.Icons.ADD,
            bgcolor=ft.Colors.BLUE_600,
            color=ft.Colors.WHITE,
            on_click=abrir_dialogo_boleto,
        )

        # ------------------------------------------------------------------
        # Fluxo de Caixa
        # ------------------------------------------------------------------

        campo_descricao_transacao = ft.TextField(
            label="Descrição",
            autofocus=True,
        )

        campo_valor_transacao = ft.TextField(
            label="Valor (R$)",
            input_filter=ft.InputFilter(
                regex_string=r"[0-9.]",
                allow=True,
            ),
        )

        campo_tipo_transacao = ft.Dropdown(
            label="Tipo",
            width=220,
            value="Receita",
            options=[
                ft.dropdown.Option("Receita"),
                ft.dropdown.Option("Despesa_Variavel"),
            ],
        )

        campo_categoria_transacao = ft.TextField(
            label="Categoria",
        )

        campo_data_transacao = ft.TextField(
            label="Data",
            hint_text="DD/MM/AAAA",
        )

        def fechar_dialogo_transacao(e=None):
            dialogo_transacao.open = False
            page.update()


        def abrir_dialogo_transacao(e=None):

            campo_descricao_transacao.value = ""
            campo_valor_transacao.value = ""
            campo_tipo_transacao.value = "Receita"
            campo_categoria_transacao.value = ""
            campo_data_transacao.value = ""

            dialogo_transacao.open = True
            page.update()

        def salvar_transacao(e):

            descricao = (campo_descricao_transacao.value or "").strip()

            if not descricao:
                notificar("Informe a descrição.", erro=True)
                return

            try:
                valor = float(
                    (campo_valor_transacao.value or "0")
                    .replace(",", ".")
                )
            except ValueError:
                notificar("Valor inválido.", erro=True)
                return

            categoria = (campo_categoria_transacao.value or "").strip()

            if not categoria:
                notificar("Informe a categoria.", erro=True)
                return

            try:
                data = datetime.strptime(
                    campo_data_transacao.value.strip(),
                    "%d/%m/%Y",
                ).strftime("%Y-%m-%d")

            except Exception:
                notificar(
                    "Data inválida. Utilize DD/MM/AAAA.",
                    erro=True,
                )
                return

            db.adicionar_transacao(
                descricao=descricao,
                valor=valor,
                tipo=campo_tipo_transacao.value,
                categoria=categoria,
                data=data,
            )

            fechar_dialogo_transacao()

            notificar("Transação cadastrada com sucesso!")

            atualizar_tela_financeiro()
        
        dialogo_transacao = ft.AlertDialog(
            modal=True,
            title=ft.Text(
                "Nova Transação",
                weight=ft.FontWeight.BOLD,
            ),
            content=ft.Column(
                tight=True,
                spacing=12,
                controls=[
                    campo_descricao_transacao,
                    campo_valor_transacao,
                    campo_tipo_transacao,
                    campo_categoria_transacao,
                    campo_data_transacao,
                ],
            ),
            actions=[
                ft.Button(
                    "Cancelar",
                    on_click=fechar_dialogo_transacao,
                ),
                ft.Button(
                    "Salvar",
                    icon=ft.Icons.SAVE,
                    bgcolor=ft.Colors.GREEN_700,
                    color=ft.Colors.WHITE,
                    on_click=salvar_transacao,
                ),
            ],
        )

        dialogos_financeiro_para_overlay.append(dialogo_transacao)

        botao_nova_transacao = ft.Button(
            "Nova Transação",
            icon=ft.Icons.ADD,
            bgcolor=ft.Colors.GREEN_700,
            color=ft.Colors.WHITE,
            on_click=abrir_dialogo_transacao,
        )


        # ------------------------------------------------------------------
        # Telas do Financeiro (chaveamento dinâmico)
        # ------------------------------------------------------------------

        tela_boletos = ft.Container(
            expand=True,
            border=ft.Border.all(1, ft.Colors.GREY_800),
            border_radius=8,
            padding=10,
            content=lista_boletos_view,
        )

        # ------------------------------------------------------------------
        # Lista dinâmica de transações
        # ------------------------------------------------------------------

        lista_transacoes_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )

        tela_fluxo = ft.Column(
    expand=True,
    spacing=15,
    controls=[

        ft.Row(
            alignment=ft.MainAxisAlignment.END,
            controls=[
                botao_nova_transacao,
            ],
        ),

        ft.Container(
            expand=True,
            border=ft.Border.all(
                1,
                ft.Colors.GREY_800,
            ),
            border_radius=10,
            padding=10,
            content=lista_transacoes_view,
        ),

    ],
)
        

        lista_metas_view = ft.ListView(
            expand=True,
            spacing=10,
            padding=10,
        )

        campo_nome_meta = ft.TextField(
            label="Nome da Meta",
        )

        campo_valor_alvo = ft.TextField(
            label="Valor Alvo",
        )

        campo_valor_inicial = ft.TextField(
            label="Valor Inicial",
            value="0",
        )

        def fechar_dialogo_meta(e=None):
            dialogo_meta.open = False
            page.update()


        def abrir_dialogo_meta(e=None):

            campo_nome_meta.value = ""
            campo_valor_alvo.value = ""
            campo_valor_inicial.value = "0"

            dialogo_meta.open = True
            page.update()

        def salvar_meta(e):

            try:

                db.adicionar_meta(

                    campo_nome_meta.value,

                    float(campo_valor_alvo.value.replace(",", ".")),

                    float(campo_valor_inicial.value.replace(",", ".")),

                )

            except Exception as ex:

                notificar(str(ex), erro=True)
                return

            fechar_dialogo_meta()

            atualizar_lista_metas()

            atualizar_tela_financeiro()

            notificar("Meta criada com sucesso!")

        dialogo_meta = ft.AlertDialog(

            modal=True,

            title=ft.Text("Nova Meta"),

            content=ft.Column(

                tight=True,

                controls=[

                    campo_nome_meta,

                    campo_valor_alvo,

                    campo_valor_inicial,

                ],

            ),

            actions=[

                ft.Button(

                    "Cancelar",

                    on_click=fechar_dialogo_meta,

                ),

                ft.Button(

                    "Salvar",

                    icon=ft.Icons.SAVE,

                    on_click=salvar_meta,

                ),

            ],

        )
        dialogos_financeiro_para_overlay.append(dialogo_meta)

        botao_nova_meta = ft.Button(

                "Nova Meta",

                icon=ft.Icons.ADD,

                bgcolor=ft.Colors.BLUE_600,

                color=ft.Colors.WHITE,

                on_click=abrir_dialogo_meta,

            )

        # --- Aporte em meta ---------------------------------------------

        estado_aporte = {"meta_id": None, "valor_atual": 0.0}

        campo_valor_aporte = ft.TextField(
            label="Valor do Aporte",
        )

        def fechar_dialogo_aporte(e=None):
            dialogo_aporte.open = False
            page.update()

        def abrir_dialogo_aporte(meta_id: int, valor_atual: float) -> None:
            estado_aporte["meta_id"] = meta_id
            estado_aporte["valor_atual"] = valor_atual
            campo_valor_aporte.value = ""
            dialogo_aporte.open = True
            page.update()

        def salvar_aporte(e):
            try:
                valor_aporte = float(campo_valor_aporte.value.replace(",", "."))
                if valor_aporte <= 0:
                    raise ValueError("O valor do aporte deve ser maior que zero.")
            except ValueError as ex:
                notificar(str(ex) or "Informe um valor válido.", erro=True)
                return

            novo_valor = estado_aporte["valor_atual"] + valor_aporte
            db.atualizar_saldo_meta(estado_aporte["meta_id"], novo_valor)

            fechar_dialogo_aporte()

            atualizar_lista_metas()
            atualizar_tela_financeiro()

            notificar("Aporte registrado com sucesso!")

        dialogo_aporte = ft.AlertDialog(
            modal=True,
            title=ft.Text("Novo Aporte"),
            content=ft.Column(
                tight=True,
                controls=[
                    campo_valor_aporte,
                ],
            ),
            actions=[
                ft.Button(
                    "Cancelar",
                    on_click=fechar_dialogo_aporte,
                ),
                ft.Button(
                    "Salvar",
                    icon=ft.Icons.SAVE,
                    on_click=salvar_aporte,
                ),
            ],
        )
        dialogos_financeiro_para_overlay.append(dialogo_aporte)

        def excluir_meta_ui(meta_id: int) -> None:
            db.deletar_meta(meta_id)
            notificar("Meta removida.")
            atualizar_lista_metas()
            atualizar_tela_financeiro()

        tela_investimentos = ft.Column(

                expand=True,

                spacing=15,

                controls=[

                    ft.Row(

                        alignment=ft.MainAxisAlignment.END,

                        controls=[

                            botao_nova_meta,

                        ],

                    ),

                    ft.Container(

                        expand=True,

                        border=ft.Border.all(

                            1,

                            ft.Colors.GREY_800,

                        ),

                        border_radius=10,

                        padding=10,

                        content=lista_metas_view,

                    ),

                ],

            )

        conteudo_financeiro = ft.Container(
            expand=True,
            content=tela_boletos,
        )
        # ------------------------------------------------------------------
        # Navegação interna do Financeiro
        # ------------------------------------------------------------------

        def mostrar_boletos(e=None):
            conteudo_financeiro.content = tela_boletos
            page.update()


        def mostrar_fluxo(e=None):
            conteudo_financeiro.content = tela_fluxo
            page.update()

        def atualizar_lista_metas():

            lista_metas_view.controls.clear()

            metas = db.listar_metas()

            if not metas:

                lista_metas_view.controls.append(

                    ft.Text(

                        "Nenhuma meta cadastrada.",

                        italic=True,

                        color=ft.Colors.GREY_500,

                    )

                )

                return

            for meta in metas:

                progresso = 0

                if meta["valor_alvo"] > 0:

                    progresso = min(

                        meta["valor_atual"] / meta["valor_alvo"],

                        1,

                    )

                card = ft.Container(

                    padding=18,

                    border_radius=14,

                    bgcolor=ft.Colors.GREY_900,

                    border=ft.Border.all(

                        1,

                        ft.Colors.GREY_800,

                    ),

                    content=ft.Column(

                        spacing=10,

                        controls=[

                            ft.Row(

                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,

                                controls=[

                                    ft.Text(

                                        meta["nome_meta"],

                                        weight=ft.FontWeight.BOLD,

                                        size=17,

                                    ),

                                    ft.Row(

                                        spacing=0,

                                        controls=[

                                            ft.IconButton(
                                                icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                                icon_color=ft.Colors.BLUE_300,
                                                tooltip="Fazer aporte",
                                                on_click=lambda e, mid=meta["id"], va=meta["valor_atual"]: abrir_dialogo_aporte(mid, va),
                                            ),

                                            ft.IconButton(
                                                icon=ft.Icons.DELETE_OUTLINE,
                                                icon_color=ft.Colors.RED_300,
                                                tooltip="Excluir meta",
                                                on_click=lambda e, mid=meta["id"]: excluir_meta_ui(mid),
                                            ),

                                        ],

                                    ),

                                ],

                            ),

                            ft.Text(

                                f"{formatar_valor(meta['valor_atual'])} de {formatar_valor(meta['valor_alvo'])}",

                            ),

                            ft.ProgressBar(

                                value=progresso,

                                height=8,

                            ),

                            ft.Text(

                                f"{progresso*100:.0f}%",

                                color=ft.Colors.GREEN_300,

                            ),

                        ],

                    ),

                )

                lista_metas_view.controls.append(card)


        def mostrar_investimentos(e=None):
            atualizar_lista_metas()
            conteudo_financeiro.content = tela_investimentos
            page.update()
        
        # ------------------------------------------------------------------
        # Empréstimos
        # ------------------------------------------------------------------

        texto_capital_emprestado = ft.Text(
            "R$ 0,00", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_300,
        )
        texto_juros_recebidos_emp = ft.Text(
            "R$ 0,00", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.GREEN_400,
        )
        texto_a_receber_emp = ft.Text(
            "R$ 0,00", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.AMBER_300,
        )
        texto_em_atraso_emp = ft.Text(
            "R$ 0,00", size=22, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_300,
        )

        linha_cards_emprestimos = ft.Row(
            spacing=16,
            controls=[
                _criar_card_financeiro(
                    "Capital Emprestado", ft.Icons.ACCOUNT_BALANCE_WALLET,
                    ft.Colors.BLUE_300, texto_capital_emprestado,
                ),
                _criar_card_financeiro(
                    "Juros Recebidos", ft.Icons.TRENDING_UP,
                    ft.Colors.GREEN_400, texto_juros_recebidos_emp,
                ),
                _criar_card_financeiro(
                    "A Receber", ft.Icons.MONETIZATION_ON,
                    ft.Colors.AMBER_300, texto_a_receber_emp,
                ),
                _criar_card_financeiro(
                    "Em Atraso", ft.Icons.TRENDING_DOWN,
                    ft.Colors.RED_300, texto_em_atraso_emp,
                ),
            ],
        )

        lista_emprestimos_view = ft.ListView(expand=True, spacing=10, padding=10)

        # --- Diálogo: Novo Empréstimo ---------------------------------------

        dropdown_cliente_emprestimo = ft.Dropdown(label="Cliente existente")

        campo_novo_cliente_nome = ft.TextField(label="Ou cadastre um novo cliente (nome)")
        campo_novo_cliente_contato = ft.TextField(label="Contato (opcional)")

        campo_valor_principal_emprestimo = ft.TextField(label="Valor emprestado (R$)")
        campo_taxa_juros_emprestimo = ft.TextField(label="Taxa de juros mensal (%)")

        dropdown_modalidade_emprestimo = ft.Dropdown(
            label="Modalidade",
            options=[
                ft.dropdown.Option(key=db.MODALIDADE_BULLET, text="Bullet (tudo em 30 dias)"),
                ft.dropdown.Option(key=db.MODALIDADE_CARENCIA, text="Carência (só juros no início)"),
                ft.dropdown.Option(key=db.MODALIDADE_PARCELADO, text="Parcelado (principal + juros)"),
            ],
        )

        campo_valor_parcela_principal_emprestimo = ft.TextField(
            label="Valor da parcela de principal (R$)",
            hint_text="Obrigatório apenas na modalidade Parcelado",
        )

        campo_data_inicio_emprestimo = ft.TextField(label="Data de início", hint_text="DD/MM/AAAA")

        def fechar_dialogo_novo_emprestimo(e=None):
            dialogo_novo_emprestimo.open = False
            page.update()

        def abrir_dialogo_novo_emprestimo(e=None):
            dropdown_cliente_emprestimo.options = [
                ft.dropdown.Option(key=str(c["id"]), text=c["nome"])
                for c in db.listar_clientes_emprestimo()
            ]
            dropdown_cliente_emprestimo.value = None
            campo_novo_cliente_nome.value = ""
            campo_novo_cliente_contato.value = ""
            campo_valor_principal_emprestimo.value = ""
            campo_taxa_juros_emprestimo.value = ""
            dropdown_modalidade_emprestimo.value = db.MODALIDADE_PARCELADO
            campo_valor_parcela_principal_emprestimo.value = ""
            campo_data_inicio_emprestimo.value = datetime.now().strftime("%d/%m/%Y")
            dialogo_novo_emprestimo.open = True
            page.update()

        def salvar_novo_emprestimo(e):
            nome_novo_cliente = (campo_novo_cliente_nome.value or "").strip()

            if nome_novo_cliente:
                cliente_id = db.adicionar_cliente_emprestimo(
                    nome_novo_cliente, (campo_novo_cliente_contato.value or "").strip(),
                )
            elif dropdown_cliente_emprestimo.value:
                cliente_id = int(dropdown_cliente_emprestimo.value)
            else:
                notificar("Selecione um cliente existente ou cadastre um novo.", erro=True)
                return

            try:
                valor_principal = float((campo_valor_principal_emprestimo.value or "0").replace(",", "."))
                taxa_percentual = float((campo_taxa_juros_emprestimo.value or "0").replace(",", "."))
            except ValueError:
                notificar("Verifique os valores numéricos informados.", erro=True)
                return

            modalidade = dropdown_modalidade_emprestimo.value
            if not modalidade:
                notificar("Selecione a modalidade do empréstimo.", erro=True)
                return

            valor_parcela_principal = None
            if modalidade == db.MODALIDADE_PARCELADO:
                try:
                    valor_parcela_principal = float(
                        (campo_valor_parcela_principal_emprestimo.value or "0").replace(",", ".")
                    )
                except ValueError:
                    notificar("Valor da parcela de principal inválido.", erro=True)
                    return

            try:
                data_inicio = datetime.strptime(
                    (campo_data_inicio_emprestimo.value or "").strip(), "%d/%m/%Y",
                ).strftime("%Y-%m-%d")
            except Exception:
                notificar("Data inválida. Utilize DD/MM/AAAA.", erro=True)
                return

            try:
                db.criar_emprestimo(
                    cliente_id=cliente_id,
                    valor_principal=valor_principal,
                    taxa_juros_mensal=taxa_percentual / 100,
                    modalidade=modalidade,
                    valor_parcela_principal=valor_parcela_principal,
                    data_inicio=data_inicio,
                )
            except ValueError as ex:
                notificar(str(ex), erro=True)
                return

            fechar_dialogo_novo_emprestimo()
            atualizar_lista_emprestimos()
            notificar("Empréstimo cadastrado com sucesso!")

        dialogo_novo_emprestimo = ft.AlertDialog(
            modal=True,
            title=ft.Text("Novo Empréstimo"),
            content=ft.Column(
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=440,
                controls=[
                    dropdown_cliente_emprestimo,
                    ft.Divider(),
                    campo_novo_cliente_nome,
                    campo_novo_cliente_contato,
                    ft.Divider(),
                    campo_valor_principal_emprestimo,
                    campo_taxa_juros_emprestimo,
                    dropdown_modalidade_emprestimo,
                    campo_valor_parcela_principal_emprestimo,
                    campo_data_inicio_emprestimo,
                ],
            ),
            actions=[
                ft.Button("Cancelar", on_click=fechar_dialogo_novo_emprestimo),
                ft.Button("Salvar", icon=ft.Icons.SAVE, on_click=salvar_novo_emprestimo),
            ],
        )
        dialogos_financeiro_para_overlay.append(dialogo_novo_emprestimo)

        botao_novo_emprestimo = ft.Button(
            "Novo Empréstimo",
            icon=ft.Icons.ADD,
            bgcolor=ft.Colors.BLUE_600,
            color=ft.Colors.WHITE,
            on_click=abrir_dialogo_novo_emprestimo,
        )

        # --- Diálogo: Registrar Pagamento de Parcela -------------------------

        estado_pagamento_parcela = {"parcela_id": None}

        campo_valor_principal_pago = ft.TextField(
            label="Valor de principal pago (R$)",
            hint_text="Deixe 0 se o cliente pagou só os juros",
        )

        def fechar_dialogo_pagamento(e=None):
            dialogo_pagamento_parcela.open = False
            page.update()

        def abrir_dialogo_pagamento(parcela_id: int, valor_principal_planejado: float) -> None:
            estado_pagamento_parcela["parcela_id"] = parcela_id
            campo_valor_principal_pago.value = f"{valor_principal_planejado:.2f}".replace(".", ",")
            dialogo_pagamento_parcela.open = True
            page.update()

        def confirmar_pagamento_parcela(e):
            try:
                valor_pago = float((campo_valor_principal_pago.value or "0").replace(",", "."))
                if valor_pago < 0:
                    raise ValueError
            except ValueError:
                notificar("Informe um valor válido.", erro=True)
                return

            db.registrar_pagamento_parcela(estado_pagamento_parcela["parcela_id"], valor_pago)
            fechar_dialogo_pagamento()
            atualizar_lista_emprestimos()
            notificar("Pagamento registrado com sucesso!")

        dialogo_pagamento_parcela = ft.AlertDialog(
            modal=True,
            title=ft.Text("Registrar Pagamento"),
            content=ft.Column(tight=True, controls=[campo_valor_principal_pago]),
            actions=[
                ft.Button("Cancelar", on_click=fechar_dialogo_pagamento),
                ft.Button(
                    "Confirmar", icon=ft.Icons.CHECK_CIRCLE_OUTLINE, on_click=confirmar_pagamento_parcela,
                ),
            ],
        )
        dialogos_financeiro_para_overlay.append(dialogo_pagamento_parcela)

        # --- Diálogo: Gerar Próxima Cobrança ---------------------------------

        estado_nova_cobranca = {"emprestimo_id": None}

        campo_valor_principal_proxima = ft.TextField(
            label="Valor de principal nesta cobrança (R$)",
            hint_text="Deixe 0 para cobrar somente os juros (prorrogação)",
        )

        def fechar_dialogo_nova_cobranca(e=None):
            dialogo_nova_cobranca.open = False
            page.update()

        def abrir_dialogo_nova_cobranca(emprestimo_id: int, valor_sugerido: float) -> None:
            estado_nova_cobranca["emprestimo_id"] = emprestimo_id
            campo_valor_principal_proxima.value = (
                f"{valor_sugerido:.2f}".replace(".", ",") if valor_sugerido else "0"
            )
            dialogo_nova_cobranca.open = True
            page.update()

        def confirmar_nova_cobranca(e):
            try:
                valor_planejado = float((campo_valor_principal_proxima.value or "0").replace(",", "."))
                if valor_planejado < 0:
                    raise ValueError
            except ValueError:
                notificar("Informe um valor válido.", erro=True)
                return

            try:
                db.gerar_proxima_parcela(estado_nova_cobranca["emprestimo_id"], valor_planejado)
            except ValueError as ex:
                notificar(str(ex), erro=True)
                return

            fechar_dialogo_nova_cobranca()
            atualizar_lista_emprestimos()
            notificar("Nova cobrança gerada!")

        dialogo_nova_cobranca = ft.AlertDialog(
            modal=True,
            title=ft.Text("Gerar Próxima Cobrança"),
            content=ft.Column(tight=True, controls=[campo_valor_principal_proxima]),
            actions=[
                ft.Button("Cancelar", on_click=fechar_dialogo_nova_cobranca),
                ft.Button(
                    "Gerar", icon=ft.Icons.ADD_CIRCLE_OUTLINE, on_click=confirmar_nova_cobranca,
                ),
            ],
        )
        dialogos_financeiro_para_overlay.append(dialogo_nova_cobranca)

        # --- Diálogo: Ficha do Cliente (com Margem de Segurança) -------------

        texto_ficha_nome_cliente = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
        texto_ficha_juros_recebidos = ft.Text("", size=14)
        texto_ficha_saldo_devedor = ft.Text("", size=14)
        texto_ficha_margem_seguranca = ft.Text("", size=15, weight=ft.FontWeight.BOLD)
        lista_ficha_historico_emprestimos = ft.ListView(height=200, spacing=8)

        def fechar_ficha_cliente(e=None):
            dialogo_ficha_cliente.open = False
            page.update()

        def abrir_ficha_cliente(cliente_id: int) -> None:
            cliente = next(
                (c for c in db.listar_clientes_emprestimo() if c["id"] == cliente_id), None,
            )
            if cliente is None:
                return

            margem_info = db.calcular_margem_seguranca(cliente_id)
            margem = margem_info["margem_seguranca"]

            texto_ficha_nome_cliente.value = cliente["nome"]
            texto_ficha_juros_recebidos.value = f"Juros recebidos (histórico): {formatar_valor(margem_info['juros_recebidos'])}"
            texto_ficha_saldo_devedor.value = f"Saldo devedor atual: {formatar_valor(margem_info['saldo_devedor'])}"

            if margem >= 0:
                texto_ficha_margem_seguranca.value = (
                    f"🛡️ Margem de segurança: {formatar_valor(margem)} — pode emprestar até "
                    f"esse valor a mais sem risco de prejuízo"
                )
                texto_ficha_margem_seguranca.color = ft.Colors.GREEN_300
            else:
                texto_ficha_margem_seguranca.value = (
                    f"⚠️ Margem de segurança: {formatar_valor(margem)} — ainda em risco, "
                    f"não recomendado emprestar mais"
                )
                texto_ficha_margem_seguranca.color = ft.Colors.RED_300

            lista_ficha_historico_emprestimos.controls.clear()
            for emp in db.listar_emprestimos_cliente(cliente_id):
                cor_status = (
                    ft.Colors.GREEN_300 if emp["status"] == db.STATUS_EMPRESTIMO_ATIVO else ft.Colors.GREY_500
                )
                lista_ficha_historico_emprestimos.controls.append(
                    ft.Container(
                        padding=10,
                        border_radius=8,
                        bgcolor=ft.Colors.GREY_900,
                        border=ft.Border.all(1, ft.Colors.GREY_800),
                        content=ft.Column(
                            spacing=4,
                            controls=[
                                ft.Text(
                                    f"{formatar_valor(emp['valor_principal'])} — {emp['modalidade']}",
                                    weight=ft.FontWeight.BOLD, size=13,
                                ),
                                ft.Text(f"Status: {emp['status']}", size=12, color=cor_status),
                                ft.Text(f"Saldo devedor: {formatar_valor(emp['saldo_devedor'])}", size=12),
                                ft.Text(f"Início: {formatar_data_br(emp['data_inicio'])}", size=12),
                            ],
                        ),
                    )
                )

            dialogo_ficha_cliente.open = True
            page.update()

        dialogo_ficha_cliente = ft.AlertDialog(
            modal=True,
            title=texto_ficha_nome_cliente,
            content=ft.Column(
                tight=True,
                scroll=ft.ScrollMode.AUTO,
                height=420,
                controls=[
                    texto_ficha_juros_recebidos,
                    texto_ficha_saldo_devedor,
                    ft.Divider(),
                    texto_ficha_margem_seguranca,
                    ft.Divider(),
                    ft.Text("Histórico de empréstimos:", weight=ft.FontWeight.BOLD, size=13),
                    lista_ficha_historico_emprestimos,
                ],
            ),
            actions=[ft.Button("Fechar", on_click=fechar_ficha_cliente)],
        )
        dialogos_financeiro_para_overlay.append(dialogo_ficha_cliente)

        # --- Atualização da lista e dos cards ---------------------------------

        def atualizar_lista_emprestimos() -> None:
            db.marcar_parcelas_atrasadas()

            resumo = db.calcular_resumo_emprestimos()
            texto_capital_emprestado.value = formatar_valor(resumo["capital_emprestado"])
            texto_juros_recebidos_emp.value = formatar_valor(resumo["juros_recebidos"])
            texto_a_receber_emp.value = formatar_valor(resumo["a_receber"])
            texto_em_atraso_emp.value = formatar_valor(resumo["em_atraso"])

            lista_emprestimos_view.controls.clear()

            emprestimos = db.listar_emprestimos_ativos()

            if not emprestimos:
                lista_emprestimos_view.controls.append(
                    ft.Text("Nenhum empréstimo ativo no momento.", italic=True, color=ft.Colors.GREY_500)
                )
                page.update()
                return

            for emp in emprestimos:
                parcelas = db.listar_parcelas_emprestimo(emp["id"])
                parcela_pendente = next(
                    (p for p in parcelas if p["status"] != db.STATUS_PARCELA_PAGO), None,
                )

                if parcela_pendente:
                    atrasada = parcela_pendente["status"] == db.STATUS_PARCELA_ATRASADO
                    cor_status = ft.Colors.RED_300 if atrasada else ft.Colors.AMBER_300
                    rotulo_status = "Atrasada" if atrasada else "Pendente"
                    valor_total_parcela = parcela_pendente["valor_juros"] + parcela_pendente["valor_principal"]

                    controles_acao = [
                        ft.Text(
                            f"Cobrança #{parcela_pendente['numero']} — {formatar_valor(valor_total_parcela)} "
                            f"(juros {formatar_valor(parcela_pendente['valor_juros'])} + "
                            f"principal {formatar_valor(parcela_pendente['valor_principal'])}) — "
                            f"venc. {formatar_data_br(parcela_pendente['data_vencimento'])} — {rotulo_status}",
                            size=12,
                            color=cor_status,
                        ),
                        ft.Button(
                            "Registrar Pagamento",
                            icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                            on_click=lambda e, pid=parcela_pendente["id"], vp=parcela_pendente["valor_principal"]: abrir_dialogo_pagamento(pid, vp),
                        ),
                    ]
                else:
                    controles_acao = [
                        ft.Button(
                            "Gerar Próxima Cobrança",
                            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                            on_click=lambda e, eid=emp["id"], vpp=(emp["valor_parcela_principal"] or 0): abrir_dialogo_nova_cobranca(eid, vpp),
                        ),
                    ]

                card = ft.Container(
                    padding=18,
                    border_radius=14,
                    bgcolor=ft.Colors.GREY_900,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Container(
                                        content=ft.Text(
                                            emp["nome_cliente"], weight=ft.FontWeight.BOLD, size=17,
                                            color=ft.Colors.BLUE_300,
                                        ),
                                        on_click=lambda e, cid=emp["cliente_id"]: abrir_ficha_cliente(cid),
                                    ),
                                    ft.Text(emp["modalidade"], size=12, color=ft.Colors.GREY_400),
                                ],
                            ),
                            ft.Text(
                                f"Emprestado: {formatar_valor(emp['valor_principal'])}  •  "
                                f"Taxa: {emp['taxa_juros_mensal'] * 100:.1f}% a.m.  •  "
                                f"Saldo devedor: {formatar_valor(emp['saldo_devedor'])}",
                                size=13,
                            ),
                            *controles_acao,
                        ],
                    ),
                )

                lista_emprestimos_view.controls.append(card)

            page.update()

        tela_emprestimos = ft.Column(
            expand=True,
            spacing=15,
            controls=[
                linha_cards_emprestimos,
                ft.Row(
                    alignment=ft.MainAxisAlignment.END,
                    controls=[botao_novo_emprestimo],
                ),
                ft.Container(
                    expand=True,
                    border=ft.Border.all(1, ft.Colors.GREY_800),
                    border_radius=10,
                    padding=10,
                    content=lista_emprestimos_view,
                ),
            ],
        )

        def mostrar_emprestimos(e=None):
            atualizar_lista_emprestimos()
            conteudo_financeiro.content = tela_emprestimos
            page.update()

        linha_seletor_financeiro = ft.Row(
    spacing=12,
    controls=[
        ft.Button(
            "💳 Boletos",
            icon=ft.Icons.RECEIPT_LONG,
            on_click=mostrar_boletos,
        ),
        ft.Button(
            "📈 Fluxo de Caixa",
            icon=ft.Icons.TRENDING_UP,
            on_click=mostrar_fluxo,
        ),
        ft.Button(
            "🎯 Investimentos",
            icon=ft.Icons.SAVINGS,
            on_click=mostrar_investimentos,
        ),
        ft.Button(
            "🤝 Empréstimos",
            icon=ft.Icons.MONETIZATION_ON,
            on_click=mostrar_emprestimos,
        ),
    ],
)

        container_financeiro = ft.Container(
            padding=30,
            content=ft.Column(
                spacing=16,
                expand=True,
                controls=[
                    ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Text("Financeiro", size=24, weight=ft.FontWeight.BOLD),
                            botao_novo_boleto,
                        ],
                    ),
                    ft.Divider(),
                    linha_cards,

ft.Row(
    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
    controls=[
        dropdown_mes_financeiro,
    ],
),

linha_seletor_financeiro,

conteudo_financeiro,
                ],
            ),
        )

        # Guarda a função de atualização e o carregamento inicial: chamada
        # aqui (dados já existentes no banco) e reaproveitada ao trocar de aba.
        estado_financeiro["atualizar"] = atualizar_tela_financeiro
        atualizar_tela_financeiro()

        return container_financeiro

    estado_financeiro = {"atualizar": None}
    dialogos_financeiro_para_overlay = []
    aba_financeiro = construir_tela_financeiro()



    conteudo_atual = ft.Container(expand=True, content=aba_dashboard)

    def ao_trocar_aba(e: ft.ControlEvent) -> None:
        indice = e.control.selected_index
        if indice == 0:
            conteudo_atual.content = aba_dashboard
            atualizar_cards_dashboard()
        elif indice == 1:
            conteudo_atual.content = aba_estudos
        elif indice == 2:
            conteudo_atual.content = aba_configuracoes
        elif indice == 3:
            conteudo_atual.content = aba_faculdade
        elif indice == 4:
            conteudo_atual.content = aba_clientes
        elif indice == 5:
            conteudo_atual.content = aba_rotina
        elif indice == 6:
            conteudo_atual.content = aba_veiculos
            construir_lista_veiculos()
        elif indice == 7:
            conteudo_atual.content = aba_financeiro
            if estado_financeiro["atualizar"]:
                estado_financeiro["atualizar"]()
        page.update()

    navegacao = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=90,
        min_extended_width=200,
        bgcolor=ft.Colors.GREY_900,
        destinations=[
            ft.NavigationRailDestination(
                icon=ft.Icons.SPACE_DASHBOARD_OUTLINED,
                selected_icon=ft.Icons.SPACE_DASHBOARD,
                label="Dashboard",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.MENU_BOOK_OUTLINED,
                selected_icon=ft.Icons.MENU_BOOK,
                label="Estudos & Editais",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SETTINGS_OUTLINED,
                selected_icon=ft.Icons.SETTINGS,
                label="Configurações",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.SCHOOL_OUTLINED,
                selected_icon=ft.Icons.SCHOOL,
                label="Faculdade",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.BUSINESS_CENTER_OUTLINED,
                selected_icon=ft.Icons.BUSINESS_CENTER,
                label="Clientes & Freelas",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                selected_icon=ft.Icons.CHECK_CIRCLE,
                label="Rotina & Hábitos",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.DIRECTIONS_CAR_OUTLINED,
                selected_icon=ft.Icons.DIRECTIONS_CAR,
                label="Veículos",
            ),
            ft.NavigationRailDestination(
                icon=ft.Icons.MONETIZATION_ON,
                selected_icon=ft.Icons.MONETIZATION_ON,
                label="Financeiro",
            ),
        ],
        on_change=ao_trocar_aba,
    )

    layout_principal = ft.Row(
        expand=True,
        spacing=0,
        controls=[
            navegacao,
            ft.VerticalDivider(width=1),
            conteudo_atual,
        ],
    )

    page.add(layout_principal)
    page.update()  # Completa o handshake inicial do controle de árvore com o cliente.

    # Só agora é seguro registrar Service controls que exigem overlay
    # visual (como o SnackBar e os AlertDialogs) — o FilePicker NÃO entra
    # aqui: ele é um Service "headless" (não visual) e se registra
    # automaticamente na página assim que é instanciado. Colocá-lo em
    # page.overlay é o que causava o erro "Unknown control: FilePicker".
    page.overlay.append(snack)
    page.overlay.append(dialogo_rendimento)
    page.overlay.append(dialogo_agendamento)
    page.overlay.append(dialogo_confirmar_exclusao_edital)
    page.overlay.append(dialogo_novo_veiculo)
    page.overlay.append(dialogo_km_veiculo)
    page.overlay.append(dialogo_confirmar_exclusao_veiculo)
    page.overlay.append(dialogo_novo_item)
    page.overlay.append(dialogo_registrar_manutencao)
    page.overlay.append(dialogo_abastecimento)
    page.overlay.append(dialogo_config_prova)
    page.overlay.append(dialogo_fonte_cronograma)
    page.overlay.append(dialogo_disciplina)
    page.overlay.append(dialogo_projeto)
    page.overlay.append(dialogo_habito)
    page.overlay.append(dialogo_tarefa)
    for _dialogo_financeiro in dialogos_financeiro_para_overlay:
        page.overlay.append(_dialogo_financeiro)
    page.update()

    # Carrega os editais já existentes no banco ao iniciar o app
    # e popula os cards do Dashboard com os números atuais.
    carregar_editais_no_dropdown()
    atualizar_cards_dashboard()

    # Popula as listas dos novos módulos (Faculdade, Clientes & Freelas,
    # Rotina & Hábitos) com os dados já existentes no banco.
    construir_lista_disciplinas()
    construir_lista_projetos()
    construir_tabela_habitos()
    construir_lista_veiculos()


if __name__ == "__main__":
    ft.app(target=main)