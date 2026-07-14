
# 🖥️ Dashboard - pessoal

Dashboard pessoal desktop, construído em **Python + Flet**, para centralizar controle financeiro, manutenção de veículos, estudos para concurso público e rotina diária em um único aplicativo — com apoio de IA (Google Gemini) para automações e análises.

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![Flet](https://img.shields.io/badge/Flet-0.85.3-6C4EE3)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 📖 Sobre o projeto

Este é um projeto pessoal desenvolvido para resolver um problema real: consolidar em um único lugar o controle de finanças, veículos, estudos e rotina, que antes estavam espalhados em planilhas, aplicativos separados e anotações soltas.

Todo o dado fica salvo localmente em **SQLite**, sem depender de serviços externos para funcionar — as poucas integrações externas (Google Gemini, Google Agenda) são opcionais e usadas apenas para funcionalidades específicas de IA e sincronização.

---

## ✨ Funcionalidades por módulo

### 💰 Financeiro
- **Boletos** — cadastro, controle de pagamento, cópia de código de barras.
- **Fluxo de Caixa** — registro de entradas e saídas, cards de balanço mensal.
- **Investimentos** — metas de investimento com acompanhamento de progresso e aportes.
- **Empréstimos** — sistema de empréstimo a terceiros com juros mensais, suporte a múltiplas modalidades de pagamento (parcela única, carência, parcelado) e cálculo de **margem de segurança por cliente** (quanto já foi recuperado em juros vs. o que ainda está em risco).

### 📚 Estudos & Editais
- Importação de editais de concurso via JSON ou **extração automática por IA** direto do PDF oficial (via Gemini).
- Estrutura hierárquica edital → matérias → tópicos, com registro de questões feitas e cálculo de percentual de acerto por tópico.
- **Meta diária de questões**, com sequência (streak) de dias cumpridos.
- **Cronograma de estudos gerado dinamicamente**: algoritmo prioriza tópicos com pior desempenho ou ainda não estudados, distribuindo o conteúdo entre a data atual e a data da prova, respeitando a capacidade diária de estudo.
- Análise de progresso assistida por IA, com recomendações de foco.

### 🚗 Veículos
- Cadastro de múltiplos veículos (carro/moto), com plano de manutenção pré-configurado com base em intervalos oficiais de fabricante.
- Acompanhamento de manutenções por km e/ou por tempo, com status automático (Em dia / Atenção / Vencido).
- Histórico de manutenções realizadas, com custo e local.
- Controle de abastecimentos com cálculo automático de consumo (km/L).

### ✅ Rotina & Hábitos
- Hábitos recorrentes com controle por dia da semana e horário sugerido.
- Tarefas planejadas com prioridade, data e horário.
- Registro separado de atividades extras/imprevistos do dia a dia.

### 🎓 Faculdade & 💼 Clientes & Freelas
- Controle de disciplinas, faltas e notas.
- Gestão de clientes e projetos freelance.

---

## 🛠️ Stack técnica

| Camada | Tecnologia |
|---|---|
| Interface | [Flet](https://flet.dev) (Python + Flutter) |
| Banco de dados | SQLite3 |
| IA | Google Gemini API (extração de PDF, análise de desempenho) |
| Integrações | Google Calendar API |
| Empacotamento | PyInstaller |

---

## 🏗️ Arquitetura

```
main.py                      → interface completa (Flet)
src/
  database/
    database.py               → camada de dados (SQLite)
  services/
    ai_service.py              → integração com Gemini
    calendar_service.py         → integração com Google Agenda
assets/                       → ícones e recursos visuais
tests/                        → dados de exemplo para testes
build_exe.py                  → script de build (PyInstaller)
```

O projeto é construído como um app desktop single-binary via PyInstaller, com todo o estado persistido localmente em SQLite — sem necessidade de servidor ou backend remoto.

---

## 🚀 Rodando localmente

```bash
# Clone o repositório
git clone https://github.com/Dilermando-Helcias/dashboard-pessoal.git
cd dashboard-pessoal

# Instale as dependências
pip install -r requirements.txt

# Execute
python main.py
```

> Algumas funcionalidades (extração de edital por IA, sincronização com Google Agenda) exigem chaves de API próprias, configuradas em variáveis de ambiente / arquivos de credencial que **não são versionados** neste repositório por segurança.

---

## 📌 Roadmap

- [ ] Relatório consolidado cruzando dados entre módulos (ex: gasto total mensal somando Financeiro + Veículos)
- [ ] Cards de resumo dos novos módulos na tela principal do Dashboard
- [ ] Exportação de relatórios em PDF

---

## 📄 Licença

Este projeto está sob a licença MIT — veja o arquivo [LICENSE](LICENSE) para mais detalhes.

---

## 👤 Autor

Desenvolvido por **José Dilermando** — projeto pessoal, construído e evoluído de forma incremental como estudo prático de desenvolvimento de software.
