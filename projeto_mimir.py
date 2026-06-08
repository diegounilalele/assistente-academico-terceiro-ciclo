from flask import Flask, request, jsonify, send_from_directory, session  # comunicação com o front-end
from werkzeug.security import check_password_hash, generate_password_hash # conferir/gerar senha com hash (vem junto do Flask)
from dotenv import load_dotenv # esconder a api / configs no .env
from pyngrok import ngrok # expor o servidor na internet (opcional)
from contextlib import contextmanager # criar o gerenciador de conexão "with"
from functools import wraps # preservar o nome das funções nos decorators
import sqlite3 # banco de dados
import requests # requisições HTTP à API do Ollama
import re
import json
import os
import time # esperar o ngrok liberar o domínio entre as tentativas

load_dotenv() # carrega as variáveis do .env


OLLAMA_URL = os.getenv("ollama_url") # URL do Ollama (local por padrão)
OLLAMA_MODEL = os.getenv("ollama_model") # modelo do Ollama
NGROK_TOKEN  = os.getenv("ngrok_token", "") # token do ngrok (opcional)
NGROK_API_KEY = os.getenv("ngrok_api_key", "") # chave da API do ngrok (opcional) p/ derrubar sessões presas
CAMINHO_BANCO = "universidade.db" # nome do arquivo do banco em um só lugar
LIMITE_CARACTERES_PERGUNTA = 1000 # tamanho máximo da pergunta
TOTAL_AULAS_PADRAO = 40 # total de aulas usado por padrão ao lançar faltas (não é mais escolhido na tela)

servidor = Flask(__name__)
servidor.secret_key = os.getenv("SEGREDOSEGREDO", "bologna") # chave que assina os cookies de sessão


@contextmanager
def conectar_db():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row # permite acessar colunas pelo nome: linha["nome"]
    conexao.execute("PRAGMA foreign_keys = ON;")  # liga o ON DELETE CASCADE
    try:
        yield conexao
        conexao.commit() # se chegou aqui sem erro, grava as alterações
    finally:
        conexao.close() # fecha a conexão de qualquer jeito


def login_obrigatorio(rota):
    @wraps(rota)
    def protegida(*args, **kwargs):
        if not session.get("usuario_tipo"):
            return jsonify({"status": "erro", "mensagem": "Faça login para continuar."}), 401
        return rota(*args, **kwargs)
    return protegida


def apenas_professor(rota):
    @wraps(rota)
    def protegida(*args, **kwargs):
        if session.get("usuario_tipo") != "professor":
            return jsonify({"status": "erro", "mensagem": "Acesso negado. Apenas professores."}), 403
        return rota(*args, **kwargs)
    return protegida


def buscar_dados_aluno(id_aluno):
    with conectar_db() as conexao:
        cursor = conexao.cursor()

        cursor.execute("SELECT nome FROM alunos WHERE id = ?", (id_aluno,))
        aluno = cursor.fetchone()
        if not aluno:
            return None  # o "with" fecha a conexão sozinho

        cursor.execute("SELECT id, materia, nota FROM notas WHERE aluno_id = ? ORDER BY materia, id", (id_aluno,))
        notas = cursor.fetchall()

        cursor.execute("SELECT materia, faltas, total_aulas FROM faltas WHERE aluno_id = ?", (id_aluno,))
        registros_faltas = cursor.fetchall()

        cursor.execute("SELECT materia, data, conteudo FROM provas WHERE aluno_id = ?", (id_aluno,))
        provas = cursor.fetchall()

        cursor.execute("SELECT texto FROM observacoes WHERE aluno_id = ?", (id_aluno,))
        registro_obs = cursor.fetchone()

    # Agrupa as notas por matéria (uma lista de notas para cada matéria)
    notas_por_materia = {}
    # Mesma coisa, mas guardando o id de cada nota (o professor precisa dele p/ editar/apagar)
    notas_detalhadas = {}
    for linha in notas:
        notas_por_materia.setdefault(linha["materia"], []).append(linha["nota"])
        notas_detalhadas.setdefault(linha["materia"], []).append({"id": linha["id"], "nota": linha["nota"]})

    # Média de cada matéria (calculada no Python para evitar erros de arredondamento do SQL)
    medias_calculadas = {
        materia: sum(lista) / len(lista)
        for materia, lista in notas_por_materia.items()
    }

    # Situação de faltas: percentual e se passou ou não do limite de 25%
    faltas_calculadas = {}
    for linha in registros_faltas:
        materia, faltadas, total = linha["materia"], linha["faltas"], linha["total_aulas"]
        percentual = (faltadas / total) * 100 if total else 0
        limite = total * 0.25
        situacao = "Frequência OK" if faltadas <= limite else "Reprovado por falta"
        faltas_calculadas[materia] = {
            "faltas": faltadas, "total": total,
            "percentual": round(percentual, 2), "situacao": situacao
        }

    # Quanto o aluno ainda precisa tirar para fechar a média mínima (nota de corte configurável)
    corte = nota_corte()
    necessario_para_passar = {}
    for materia, media_atual in medias_calculadas.items():
        if media_atual < corte:
            qtd_notas = len(notas_por_materia[materia])
            soma_atual = sum(notas_por_materia[materia])
            # (média_alvo * (qtd_notas + 1)) - soma_atual = nota necessária na próxima avaliação
            nota_necessaria = (corte * (qtd_notas + 1)) - soma_atual
            necessario_para_passar[materia] = min(round(nota_necessaria, 2), 10.0)
        else:
            necessario_para_passar[materia] = "Média atingida"

    # Alertas automáticos de faltas (crítico quando reprovou, atenção a partir de 20%)
    alertas_faltas = []
    for materia, info in faltas_calculadas.items():
        if info["situacao"] == "Reprovado por falta":
            alertas_faltas.append(f"REPROVADO POR FALTA em {materia}")
        elif info["percentual"] >= 20.0:
            alertas_faltas.append(f"ATENÇÃO: {materia} com {info['percentual']}% de faltas (limite: 25%)")

    return {
        "nome": aluno["nome"],
        "medias": medias_calculadas,
        "faltas": faltas_calculadas,
        "provas": [
            {"materia": p["materia"], "data": p["data"], "conteudo": p["conteudo"]}
            for p in provas
        ],
        "necessario_para_passar": necessario_para_passar,
        "alertas_faltas": alertas_faltas,
        "notas_por_materia": notas_por_materia,
        "notas_detalhadas": notas_detalhadas,
        "observacao": registro_obs["texto"] if registro_obs else "",
        "nota_corte": corte,
    }

def inicializar_banco():
    with conectar_db() as conexao:
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS historico_chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                role TEXT,
                conteudo TEXT,
                data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        # Lista de conversas da barra lateral, salva por usuário (em JSON).
        # Chave = usuario_id (funciona pra todos, inclusive professor); aluno_id
        # registra de qual aluno é a conversa (fica NULL para o professor).
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS conversas_salvas (
                usuario_id INTEGER PRIMARY KEY,
                aluno_id INTEGER,
                dados TEXT,
                atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)
        # Migração: bancos que já tinham a tabela sem a coluna aluno_id ganham ela agora.
        colunas = [c["name"] for c in conexao.execute("PRAGMA table_info(conversas_salvas)").fetchall()]
        if "aluno_id" not in colunas:
            conexao.execute("ALTER TABLE conversas_salvas ADD COLUMN aluno_id INTEGER")

        # Recado/observação que o professor deixa para um aluno (um por aluno).
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS observacoes (
                aluno_id INTEGER PRIMARY KEY,
                texto TEXT,
                atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
            )
        """)
        # Configurações do sistema em pares chave/valor (ex.: nota_corte da aprovação).
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS config (
                chave TEXT PRIMARY KEY,
                valor TEXT
            )
        """)
        # Anotações pessoais (bloco de notas) de cada usuário, guardadas em JSON.
        conexao.execute("""
            CREATE TABLE IF NOT EXISTS anotacoes (
                usuario_id INTEGER PRIMARY KEY,
                dados TEXT,
                atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
            )
        """)


def get_config(chave, padrao=None):
    """Lê uma configuração da tabela config; devolve `padrao` se não existir."""
    with conectar_db() as conexao:
        linha = conexao.execute("SELECT valor FROM config WHERE chave = ?", (chave,)).fetchone()
    return linha["valor"] if linha else padrao


def set_config(chave, valor):
    """Grava (ou atualiza) uma configuração na tabela config."""
    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO config (chave, valor) VALUES (?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
            (chave, str(valor))
        )


def nota_corte():
    """Nota mínima para aprovação (configurável pelo professor; padrão 6.0)."""
    try:
        return float(get_config("nota_corte", 6.0))
    except (TypeError, ValueError):
        return 6.0


# Histórico de conversa por conta de login (usuario_id), agora guardado no banco.
def historico_do(id_usuario):
    if not id_usuario:
        return []
    with conectar_db() as conexao:
        linhas = conexao.execute(
            "SELECT role, conteudo FROM historico_chat WHERE usuario_id = ? ORDER BY id DESC LIMIT 10",
            (id_usuario,)
        ).fetchall()
    # vieram do mais novo para o mais antigo; inverte para ficar na ordem da conversa
    return [{"role": linha["role"], "content": linha["conteudo"]} for linha in reversed(linhas)]


def salvar_mensagem(id_usuario, role, conteudo):
    """Grava uma mensagem (do usuário ou da IA) no histórico do banco."""
    if not id_usuario:
        return
    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO historico_chat (usuario_id, role, conteudo) VALUES (?, ?, ?)",
            (id_usuario, role, conteudo)
        )


def texto_dados_aluno(dados):
    linhas = [f"Nome do aluno: {dados['nome']}"]

    if dados["medias"]:
        linhas.append("\nNotas e médias por matéria:")
        for materia, media in dados["medias"].items():
            notas = ", ".join(str(n) for n in dados["notas_por_materia"][materia])
            linhas.append(f"  - {materia}: notas [{notas}] | média {round(media, 2)}")

    if dados["necessario_para_passar"]:
        linhas.append("\nO que falta para fechar média 6.0:")
        for materia, valor in dados["necessario_para_passar"].items():
            if valor == "Média atingida":
                linhas.append(f"  - {materia}: média já atingida")
            else:
                linhas.append(f"  - {materia}: precisa tirar {valor} na próxima avaliação")

    if dados["faltas"]:
        linhas.append("\nFaltas por matéria:")
        for materia, info in dados["faltas"].items():
            linhas.append(f"  - {materia}: {info['faltas']}/{info['total']} aulas ({info['percentual']}%) - {info['situacao']}")

    if dados["alertas_faltas"]:
        linhas.append("\nAlertas de frequência:")
        for alerta in dados["alertas_faltas"]:
            linhas.append(f"  - {alerta}")

    if dados["provas"]:
        linhas.append("\nProvas agendadas:")
        for p in dados["provas"]:
            linhas.append(f"  - {p['materia']} em {p['data']}: {p['conteudo']}")

    if dados.get("observacao"):
        linhas.append(f"\nRecado do professor para este aluno: {dados['observacao']}")

    return "\n".join(linhas)


def condicionais(pergunta, id_usuario, id_aluno, eh_professor=False):
    if not pergunta or not pergunta.strip():
        return {"tipo": "resposta", "texto": "Por favor, digite uma pergunta."}

    # Validação: limite de caracteres
    if len(pergunta) > LIMITE_CARACTERES_PERGUNTA:
        return {"tipo": "resposta", "texto": f"Pergunta muito longa. O limite é {LIMITE_CARACTERES_PERGUNTA} caracteres."}

    # Histórico é por conta de login (id_usuario) e vem do banco (sobrevive a reinícios).
    # historico_anterior = só o que já foi gravado; mensagens = inclui a pergunta atual.
    historico_anterior = historico_do(id_usuario)
    mensagens = historico_anterior + [{"role": "user", "content": pergunta}]

    # Monta o contexto que a IA vai conhecer sobre quem está conversando.
    if eh_professor:
        # Professor não é aluno: não tem notas/faltas próprias e não impersonamos nenhum aluno.
        contexto_usuario = (
            "O usuário logado é um PROFESSOR (não um aluno). "
            "Ele não possui nome de aluno, notas, faltas ou provas próprias. "
            "Trate-o como professor e ajude com dúvidas de tecnologia e sobre o uso do sistema."
        )
    else:
        # Aluno: por privacidade, só entregamos os dados DESTE aluno (não os de outros).
        dados_aluno = buscar_dados_aluno(id_aluno) if id_aluno else None
        contexto_usuario = (
            texto_dados_aluno(dados_aluno) if dados_aluno
            else "Não há dados acadêmicos vinculados a este usuário."
        )

    sabio = f"""
Você é o assistente virtual de um sistema acadêmico universitário. Você conhece as informações de quem está logado (abaixo) e também domina assuntos de tecnologia. Se o usuario mandar meu brasil, responda fui enganado.

INFORMAÇÕES SOBRE O USUÁRIO LOGADO (use para responder sobre nome, notas, médias, faltas e provas)
{contexto_usuario}
FIM DAS INFORMAÇÕES 

Regras sobre os dados pessoais:
- Quando perguntarem sobre o próprio nome, notas, médias, faltas, provas ou o que falta para passar, responda usando EXATAMENTE as informações acima.
- Não invente nada que não esteja nas informações acima. Se não estiver lá, diga que não tem essa informação.
- Você só conhece os dados deste usuário. Não tem acesso aos dados de outros alunos.

Você também domina todos os assuntos de tecnologia, incluindo:
Programação (Python, JavaScript, C, Java, SQL, e qualquer outra linguagem)
Banco de dados, APIs, servidores e redes
Inteligência artificial e machine learning
Hardware, sistemas operacionais e segurança
Desenvolvimento web, mobile e desktop
DevOps, cloud e ferramentas de desenvolvimento
Para perguntas de tecnologia, responda de forma técnica e didática.

Histórico recente da conversa: {json.dumps(historico_anterior, ensure_ascii=False)}

Pergunta do usuário: "{pergunta}"

Responda SOMENTE com um JSON válido, sem texto extra:
{{"tipo": "resposta", "texto": "<sua resposta aqui>"}}
Caso não for um json válido, responda:
{{"tipo": "resposta", "texto": "Desculpe, não consigo responder essa pergunta."}}
"""
    try:
        resposta = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [
                    {"role": "system", "content": sabio}, # instruções do assistente
                    *mensagens # histórico anterior + pergunta atual
                ],
                "stream": False,
                "keep_alive": "30m"  # mantém o modelo na RAM por 30 min (evita recarregar a cada pergunta)
            },
            timeout=300  # CPU + modelo grande podem demorar; tempo generoso pra não cortar a resposta
        )
        resposta.raise_for_status()
        texto = resposta.json()["message"]["content"].strip()
        texto = re.sub(r"```json|```", "", texto).strip() # tira blocos de código caso o modelo use
        resultado = json.loads(texto)

        # Só grava no banco quando a IA respondeu com sucesso (pergunta + resposta).
        salvar_mensagem(id_usuario, "user", pergunta)
        salvar_mensagem(id_usuario, "assistant", resultado.get("texto", ""))
        return resultado

    except requests.exceptions.ConnectionError:
        return {"tipo": "resposta", "texto": "Não foi possível conectar ao Ollama. Verifique se ele está rodando e se a URL está correta no .env."}
    except requests.exceptions.Timeout:
        return {"tipo": "resposta", "texto": "O Ollama demorou demais para responder. Tente novamente."}
    except Exception as e:
        return {"tipo": "resposta", "texto": f"Erro ao consultar IA: {str(e)}"}


@servidor.route("/")
def index():
    return send_from_directory(".", "index.html")


@servidor.route("/login", methods=["POST"])
def login():
    dados = request.get_json() or {}
    username = (dados.get("username") or "").strip()
    senha = dados.get("senha") or ""

    if not username or not senha:
        return jsonify({"status": "erro", "mensagem": "Informe usuário e senha."}), 400

    with conectar_db() as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT id, senha, tipo, aluno_id FROM usuarios WHERE username = ?",
            (username,)
        )
        usuario = cursor.fetchone()

    # check_password_hash compara a senha digitada com o hash salvo (nunca guardamos a senha pura)
    if usuario and check_password_hash(usuario["senha"], senha):
        session["usuario_id"]   = usuario["id"]
        session["usuario_tipo"] = usuario["tipo"]
        session["username"] = username
        session["aluno_id"] = usuario["aluno_id"]
        return jsonify({
            "status": "sucesso",
            "tipo": usuario["tipo"],
            "username": username,
            "mensagem": "Login realizado!"
        })

    return jsonify({"status": "erro", "mensagem": "Usuário ou senha incorretos."}), 401


@servidor.route("/logout", methods=["POST"])
def logout():
    session.clear()  # apaga os dados de login da sessão (cookie)
    return jsonify({"status": "sucesso", "mensagem": "Você saiu do sistema."})


@servidor.route("/sessao", methods=["GET"])
def sessao():
    """O front-end usa para saber, ao abrir a página, se o usuário já está logado."""
    if session.get("usuario_tipo"):
        return jsonify({
            "logado": True,
            "tipo": session.get("usuario_tipo"),
            "username": session.get("username")
        })
    return jsonify({"logado": False})


@servidor.route("/dados_aluno", methods=["GET"])
@login_obrigatorio
def dados_aluno_route():
    """Entrega ao HTML todos os dados já calculados do aluno logado."""
    id_aluno = session.get("aluno_id")  # professor não tem aluno vinculado -> None
    if id_aluno is None:
        return jsonify({"status": "erro", "mensagem": "Sua conta não está vinculada a um aluno."}), 400

    dados = buscar_dados_aluno(id_aluno)
    if not dados:
        return jsonify({"status": "erro", "mensagem": "Aluno não encontrado."}), 404

    dados["status"] = "sucesso"
    return jsonify(dados)


@servidor.route("/perguntar", methods=["POST"])
@login_obrigatorio
def perguntar():
    dados = request.get_json() or {}
    pergunta = dados.get("pergunta", "")
    eh_professor = session.get("usuario_tipo") == "professor"
    # id_usuario = chave do histórico (por conta); aluno_id = de quem buscar os dados (None para professor).
    return jsonify(condicionais(pergunta, session.get("usuario_id"), session.get("aluno_id"), eh_professor))


@servidor.route("/resetar", methods=["POST"])
@login_obrigatorio
def resetar():
    with conectar_db() as conexao:
        conexao.execute("DELETE FROM historico_chat WHERE usuario_id = ?", (session.get("usuario_id"),))
    return jsonify({"status": "ok", "mensagem": "Histórico resetado."})


@servidor.route("/titulo_conversa", methods=["POST"])
@login_obrigatorio
def titulo_conversa():
    dados = request.get_json() or {}
    mensagens = dados.get("mensagens") or []
    if not mensagens:
        return jsonify({"status": "erro", "titulo": ""}), 400

    # Junta a conversa (limitada) num texto só para o modelo resumir
    conversa = "\n".join(
        f"{'Usuario' if m.get('role') in ('user', 'usuario') else 'Assistente'}: {m.get('content', '')}"
        for m in mensagens[:6]
    )[:2000]

    prompt = (
        "Resuma o ASSUNTO da conversa abaixo em um título curto de no máximo 5 palavras, "
        "em português, sem aspas e sem ponto final. Responda APENAS com o título, nada mais.\n\n"
        f"{conversa}"
    )
    try:
        resposta = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "keep_alive": "30m",
            },
            timeout=120,
        )
        resposta.raise_for_status()
        titulo = (resposta.json().get("message", {}).get("content") or "").strip()
        titulo = titulo.splitlines()[0] if titulo else ""           # só a 1ª linha
        titulo = re.sub(r'^[\s"\'`#*\-]+|[\s"\'`]+$', "", titulo)    # tira aspas/markdown das pontas
        return jsonify({"status": "sucesso", "titulo": titulo[:60]})
    except Exception:
        return jsonify({"status": "erro", "titulo": ""})


@servidor.route("/conversas", methods=["GET"])
@login_obrigatorio
def obter_conversas():
    with conectar_db() as conexao:
        linha = conexao.execute(
            "SELECT dados FROM conversas_salvas WHERE usuario_id = ?",
            (session.get("usuario_id"),)
        ).fetchone()
    conversas = json.loads(linha["dados"]) if linha and linha["dados"] else []
    return jsonify({"status": "sucesso", "conversas": conversas})


@servidor.route("/conversas", methods=["POST"])
@login_obrigatorio
def salvar_conversas():
    """Salva (substitui) a lista de conversas do usuário logado. Chamado pelo front
    a cada mensagem nova / conversa arquivada, então nada se perde ao fechar o servidor."""
    dados = request.get_json() or {}
    conversas = dados.get("conversas", [])
    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO conversas_salvas (usuario_id, aluno_id, dados, atualizado_em) "
            "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(usuario_id) DO UPDATE SET "
            "aluno_id = excluded.aluno_id, dados = excluded.dados, atualizado_em = CURRENT_TIMESTAMP",
            (session.get("usuario_id"), session.get("aluno_id"), json.dumps(conversas, ensure_ascii=False))
        )
    return jsonify({"status": "sucesso"})


@servidor.route("/anotacoes", methods=["GET"])
@login_obrigatorio
def obter_anotacoes():
    with conectar_db() as conexao:
        linha = conexao.execute(
            "SELECT dados FROM anotacoes WHERE usuario_id = ?",
            (session.get("usuario_id"),)
        ).fetchone()
    anotacoes = json.loads(linha["dados"]) if linha and linha["dados"] else []
    return jsonify({"status": "sucesso", "anotacoes": anotacoes})


@servidor.route("/anotacoes", methods=["POST"])
@login_obrigatorio
def salvar_anotacoes():
    """Salva (substitui) as anotações do usuário logado, em JSON. Chamado a cada
    alteração no bloco de notas, então nada se perde ao fechar o servidor."""
    dados = request.get_json() or {}
    anotacoes = dados.get("anotacoes", [])
    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO anotacoes (usuario_id, dados, atualizado_em) "
            "VALUES (?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(usuario_id) DO UPDATE SET "
            "dados = excluded.dados, atualizado_em = CURRENT_TIMESTAMP",
            (session.get("usuario_id"), json.dumps(anotacoes, ensure_ascii=False))
        )
    return jsonify({"status": "sucesso"})


@servidor.route("/cadastrar_nota", methods=["POST"])
@apenas_professor
def cadastrar_nota():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    materia = dados.get("materia")
    nota = dados.get("nota")

    if not id_aluno or not materia or nota is None:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO notas (aluno_id, materia, nota) VALUES (?, ?, ?)",
            (id_aluno, materia, nota)
        )
    return jsonify({"status": "sucesso", "mensagem": f"Nota cadastrada para o aluno {id_aluno}!"})


@servidor.route("/todos_alunos", methods=["GET"])
@apenas_professor
def todos_alunos():
    """Painel do professor: devolve todos os alunos já com média geral, frequência e situação calculadas."""
    corte = nota_corte()
    with conectar_db() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
        lista = cursor.fetchall()

    alunos = []
    for registro in lista:
        # Reaproveita o mesmo cálculo usado na tela do aluno (médias, faltas, situação)
        dados = buscar_dados_aluno(registro["id"])
        if not dados:
            continue

        medias = list(dados["medias"].values())
        media_geral = round(sum(medias) / len(medias), 1) if medias else 0

        total_faltas = sum(f["faltas"] for f in dados["faltas"].values())
        total_aulas  = sum(f["total"]  for f in dados["faltas"].values())
        freq_geral = round((total_aulas - total_faltas) / total_aulas * 100) if total_aulas else 0

        # Uma disciplina entra "em risco" se a média ficou abaixo da nota de corte ou se reprovou por falta
        em_risco = {m for m, media in dados["medias"].items() if media < corte}
        em_risco |= {m for m, f in dados["faltas"].items() if f["situacao"] == "Reprovado por falta"}

        alunos.append({
            "id": registro["id"],
            "nome": dados["nome"],
            "media_geral": media_geral,
            "frequencia_geral": freq_geral,
            "total_disciplinas": len(dados["medias"]),
            "em_risco": sorted(em_risco),
            "medias": dados["medias"],
            "faltas": dados["faltas"],
            "notas_por_materia": dados["notas_por_materia"],  # todas as notas, para o professor ver cada uma
            "notas_detalhadas": dados["notas_detalhadas"],    # cada nota com seu id (para editar/apagar)
            "observacao": dados.get("observacao", ""),
        })

    total = len(alunos)
    resumo = {
        "total_alunos": total,
        "media_turma": round(sum(a["media_geral"] for a in alunos) / total, 1) if total else 0,
        "frequencia_media": round(sum(a["frequencia_geral"] for a in alunos) / total) if total else 0,
        "alunos_em_risco": sum(1 for a in alunos if a["em_risco"]),
    }

    return jsonify({"status": "sucesso", "alunos": alunos, "resumo": resumo, "nota_corte": corte, "total_aulas_padrao": TOTAL_AULAS_PADRAO})


@servidor.route("/cadastrar_falta", methods=["POST"])
@apenas_professor
def cadastrar_falta():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    materia = (dados.get("materia") or "").strip()
    faltas = dados.get("faltas")
    total = dados.get("total_aulas") or TOTAL_AULAS_PADRAO   # usa o padrão quando não vem da tela

    if not id_aluno or not materia or faltas is None:
        return jsonify({"status": "erro", "mensagem": "Preencha aluno, matéria e faltas."}), 400
    if total <= 0 or faltas < 0 or faltas > total:
        return jsonify({"status": "erro", "mensagem": f"Faltas devem estar entre 0 e {total}."}), 400

    # PK é (aluno_id, materia): INSERT OR REPLACE atualiza se já existir.
    with conectar_db() as conexao:
        conexao.execute(
            "INSERT OR REPLACE INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?, ?, ?, ?)",
            (id_aluno, materia, faltas, total)
        )
    return jsonify({"status": "sucesso", "mensagem": "Faltas registradas!"})


@servidor.route("/apagar_falta", methods=["POST"])
@apenas_professor
def apagar_falta():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    materia = (dados.get("materia") or "").strip()
    if not id_aluno or not materia:
        return jsonify({"status": "erro", "mensagem": "Informe aluno e matéria."}), 400

    with conectar_db() as conexao:
        cur = conexao.execute("DELETE FROM faltas WHERE aluno_id = ? AND materia = ?", (id_aluno, materia))
    if cur.rowcount == 0:
        return jsonify({"status": "erro", "mensagem": "Registro de faltas não encontrado."}), 404
    return jsonify({"status": "sucesso", "mensagem": "Faltas removidas!"})


@servidor.route("/cadastrar_prova", methods=["POST"])
@apenas_professor
def cadastrar_prova():
    dados = request.get_json() or {}
    alvo = dados.get("aluno_id")
    materia = (dados.get("materia") or "").strip()
    data = (dados.get("data") or "").strip()
    conteudo = (dados.get("conteudo") or "").strip()

    if not alvo or not materia or not data:
        return jsonify({"status": "erro", "mensagem": "Preencha aluno, matéria e data."}), 400

    with conectar_db() as conexao:
        if alvo == "turma":
            ids = [r["id"] for r in conexao.execute("SELECT id FROM alunos").fetchall()]
        else:
            ids = [int(alvo)]
        for aid in ids:
            conexao.execute(
                "INSERT OR REPLACE INTO provas (aluno_id, materia, data, conteudo) VALUES (?, ?, ?, ?)",
                (aid, materia, data, conteudo)
            )
    return jsonify({"status": "sucesso", "mensagem": f"Prova agendada para {len(ids)} aluno(s)!"})


@servidor.route("/editar_nota", methods=["POST"])
@apenas_professor
def editar_nota():
    dados = request.get_json() or {}
    nota_id = dados.get("nota_id")
    nova = dados.get("nota")

    if not nota_id or nova is None:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400
    if nova < 0 or nova > 10:
        return jsonify({"status": "erro", "mensagem": "A nota deve estar entre 0 e 10."}), 400

    with conectar_db() as conexao:
        cur = conexao.execute("UPDATE notas SET nota = ? WHERE id = ?", (nova, nota_id))
    if cur.rowcount == 0:
        return jsonify({"status": "erro", "mensagem": "Nota não encontrada."}), 404
    return jsonify({"status": "sucesso", "mensagem": "Nota atualizada!"})


@servidor.route("/apagar_nota", methods=["POST"])
@apenas_professor
def apagar_nota():
    dados = request.get_json() or {}
    nota_id = dados.get("nota_id")
    if not nota_id:
        return jsonify({"status": "erro", "mensagem": "Informe a nota."}), 400

    with conectar_db() as conexao:
        cur = conexao.execute("DELETE FROM notas WHERE id = ?", (nota_id,))
    if cur.rowcount == 0:
        return jsonify({"status": "erro", "mensagem": "Nota não encontrada."}), 404
    return jsonify({"status": "sucesso", "mensagem": "Nota apagada!"})


@servidor.route("/cadastrar_aluno", methods=["POST"])
@apenas_professor
def cadastrar_aluno():
    dados = request.get_json() or {}
    nome = (dados.get("nome") or "").strip()
    username = (dados.get("username") or "").strip()
    senha = dados.get("senha") or ""

    if not nome or not username or not senha:
        return jsonify({"status": "erro", "mensagem": "Preencha nome, usuário e senha."}), 400

    with conectar_db() as conexao:
        existe = conexao.execute("SELECT 1 FROM usuarios WHERE username = ?", (username,)).fetchone()
        if existe:
            return jsonify({"status": "erro", "mensagem": "Esse nome de usuário já existe."}), 409
        # alunos.id é INTEGER PRIMARY KEY: o SQLite gera o id sozinho.
        cur = conexao.execute("INSERT INTO alunos (nome) VALUES (?)", (nome,))
        novo_id = cur.lastrowid
        conexao.execute(
            "INSERT INTO usuarios (username, senha, tipo, aluno_id) VALUES (?, ?, 'aluno', ?)",
            (username, generate_password_hash(senha), novo_id)
        )
    return jsonify({"status": "sucesso", "mensagem": f"Aluno {nome} cadastrado (id {novo_id})!"})


@servidor.route("/resetar_senha", methods=["POST"])
@apenas_professor
def resetar_senha():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    nova = dados.get("senha") or ""

    if not id_aluno or not nova:
        return jsonify({"status": "erro", "mensagem": "Informe o aluno e a nova senha."}), 400

    with conectar_db() as conexao:
        cur = conexao.execute(
            "UPDATE usuarios SET senha = ? WHERE aluno_id = ? AND tipo = 'aluno'",
            (generate_password_hash(nova), id_aluno)
        )
    if cur.rowcount == 0:
        return jsonify({"status": "erro", "mensagem": "Esse aluno não tem um login para resetar."}), 404
    return jsonify({"status": "sucesso", "mensagem": "Senha redefinida!"})


@servidor.route("/mudar_senha", methods=["POST"])
@login_obrigatorio
def mudar_senha():
    """O próprio usuário logado troca a sua senha (confere a senha atual antes)."""
    dados = request.get_json() or {}
    atual = dados.get("senha_atual") or ""
    nova = dados.get("senha_nova") or ""

    if not atual or not nova:
        return jsonify({"status": "erro", "mensagem": "Preencha a senha atual e a nova."}), 400
    if len(nova) < 3:
        return jsonify({"status": "erro", "mensagem": "A nova senha é muito curta."}), 400

    uid = session.get("usuario_id")
    with conectar_db() as conexao:
        linha = conexao.execute("SELECT senha FROM usuarios WHERE id = ?", (uid,)).fetchone()
        if not linha or not check_password_hash(linha["senha"], atual):
            return jsonify({"status": "erro", "mensagem": "Senha atual incorreta."}), 403
        conexao.execute("UPDATE usuarios SET senha = ? WHERE id = ?", (generate_password_hash(nova), uid))
    return jsonify({"status": "sucesso", "mensagem": "Senha alterada com sucesso!"})


@servidor.route("/observacao", methods=["POST"])
@apenas_professor
def salvar_observacao():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    texto = (dados.get("texto") or "").strip()

    if not id_aluno:
        return jsonify({"status": "erro", "mensagem": "Informe o aluno."}), 400

    with conectar_db() as conexao:
        if texto:
            conexao.execute(
                "INSERT OR REPLACE INTO observacoes (aluno_id, texto) VALUES (?, ?)",
                (id_aluno, texto)
            )
        else:
            conexao.execute("DELETE FROM observacoes WHERE aluno_id = ?", (id_aluno,))
    return jsonify({"status": "sucesso", "mensagem": "Observação salva!"})


@servidor.route("/config", methods=["POST"])
@apenas_professor
def salvar_configuracao():
    dados = request.get_json() or {}
    corte = dados.get("nota_corte")
    if corte is None:
        return jsonify({"status": "erro", "mensagem": "Informe a nota de corte."}), 400
    try:
        corte = float(corte)
    except (TypeError, ValueError):
        return jsonify({"status": "erro", "mensagem": "Nota de corte inválida."}), 400
    if corte < 0 or corte > 10:
        return jsonify({"status": "erro", "mensagem": "A nota de corte deve estar entre 0 e 10."}), 400

    set_config("nota_corte", corte)
    return jsonify({"status": "sucesso", "mensagem": f"Nota de corte definida em {corte}.", "nota_corte": corte})


def liberar_sessoes_ngrok(api_key):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Ngrok-Version": "2",
        "Content-Type": "application/json",
    }
    try:
        # (1) encerra sessões de agente (cada uma leva junto seus túneis efêmeros)
        sessoes = requests.get(
            "https://api.ngrok.com/tunnel_sessions", headers=headers, timeout=15
        ).json().get("tunnel_sessions", [])
        for sessao in sessoes:
            sid = sessao.get("id")
            if sid:
                requests.post(
                    f"https://api.ngrok.com/tunnel_sessions/{sid}/stop",
                    headers=headers, json={"id": sid}, timeout=15
                )

        # (2) apaga cloud endpoints fixos (não dependem de agente e bloqueiam o domínio)
        endpoints = requests.get(
            "https://api.ngrok.com/endpoints", headers=headers, timeout=15
        ).json().get("endpoints", [])
        apagados = 0
        for ep in endpoints:
            if ep.get("type") == "cloud" and ep.get("id"):
                requests.delete(f"https://api.ngrok.com/endpoints/{ep['id']}", headers=headers, timeout=15)
                apagados += 1

        if sessoes or apagados:
            print(f"ngrok: dominio liberado (sessoes encerradas: {len(sessoes)}, cloud endpoints apagados: {apagados}).")
    except Exception as e:
        print(f"ngrok: nao consegui limpar pela API ({e}). Tentando conectar mesmo assim.")


def conectar_ngrok(tentativas=4, espera=3):
    """Abre o túnel do ngrok com algumas tentativas: depois de encerrar a sessão antiga,
    o ngrok leva alguns segundos para liberar o domínio."""
    ultimo_erro = None
    for tentativa in range(tentativas):
        try:
            return ngrok.connect(5000)
        except Exception as e:
            ultimo_erro = e
            if tentativa < tentativas - 1:
                time.sleep(espera)
    raise ultimo_erro


inicializar_banco()  # garante a tabela do histórico (roda tanto ao executar quanto ao importar)


if __name__ == "__main__": # Verifica se este arquivo está sendo executado diretamente (python projeto_mimir.py) ou importado por outro (import projeto_mimir)
    usar_ngrok = os.getenv("USAR_NGROK", "false").lower() == "true"

    if usar_ngrok:
        if NGROK_TOKEN:
            ngrok.set_auth_token(NGROK_TOKEN)
        if NGROK_API_KEY:
            liberar_sessoes_ngrok(NGROK_API_KEY)  # derruba sessões presas antes de conectar
        try:
            ngrok.kill()  # fecha túneis abertos por este processo numa execução anterior
            tunnel = conectar_ngrok()
            print(f"\nURL pública (ngrok): {tunnel.public_url}\n")
        except Exception as e:
            print(f"\nAviso: ngrok falhou ({e}). Rodando só local em http://localhost:5000\n")
    else:
        print("\nServidor local: http://localhost:5000\n")

    servidor.run(debug=True, use_reloader=False)
