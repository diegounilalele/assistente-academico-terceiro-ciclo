import sqlite3
import random  # gerar notas/faltas variadas dos alunos extras
import json  # ler o dados_exportados.json (dados reais salvos em outra máquina)
import os  # verificar se o arquivo de exportação existe
from werkzeug.security import generate_password_hash  # transforma a senha em hash (vem junto do Flask)

ARQUIVO_DADOS = "dados_exportados.json"  # gerado pelo exportar_dados.py; se existir, vence os dados de exemplo

conn = sqlite3.connect("universidade.db")
cursor = conn.cursor()

# Ativa o suporte a chaves estrangeiras (ON DELETE CASCADE)
cursor.execute("PRAGMA foreign_keys = ON;")

# Cria as tabelas SOMENTE SE ainda não existirem.
# IMPORTANTE: NÃO existe mais "DROP TABLE" aqui. Rodar este arquivo de novo
# NÃO apaga histórico nem notas já cadastradas — os dados são preservados.
cursor.executescript("""
    CREATE TABLE IF NOT EXISTS alunos (
        id INTEGER PRIMARY KEY,
        nome TEXT
    );

    CREATE TABLE IF NOT EXISTS notas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        aluno_id INTEGER,
        materia TEXT,
        nota REAL,
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS faltas (
        aluno_id INTEGER,
        materia TEXT,
        faltas INTEGER,
        total_aulas INTEGER,
        PRIMARY KEY (aluno_id, materia),
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        senha TEXT,
        tipo TEXT,
        aluno_id INTEGER,
        nome_exibicao TEXT,
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS provas (
        aluno_id INTEGER,
        materia TEXT,
        data TEXT,
        conteudo TEXT,
        PRIMARY KEY (aluno_id, materia),
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS historico_chat (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        role TEXT,
        conteudo TEXT,
        data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS conversas_salvas (
        usuario_id INTEGER PRIMARY KEY,
        aluno_id INTEGER,
        dados TEXT,
        atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS observacoes (
        aluno_id INTEGER PRIMARY KEY,
        texto TEXT,
        atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS config (
        chave TEXT PRIMARY KEY,
        valor TEXT
    );

    CREATE TABLE IF NOT EXISTS anotacoes (
        usuario_id INTEGER PRIMARY KEY,
        dados TEXT,
        atualizado_em DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
    );
""")

# Só popula com os dados de exemplo se o banco estiver VAZIO (primeira vez).
# Se já houver usuários, não mexe em nada — preserva histórico, notas, etc.
ja_tem_dados = cursor.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0

if ja_tem_dados:
    print("Banco já existe — dados preservados (nada foi recriado).")
elif os.path.exists(ARQUIVO_DADOS):
    # Banco vazio + dados_exportados.json presente: aplica os dados REAIS salvos
    # em outra máquina (senhas alteradas, notas editadas, provas/eventos, histórico...)
    # em vez dos dados de exemplo lá de baixo.
    with open(ARQUIVO_DADOS, "r", encoding="utf-8") as arquivo:
        dados_salvos = json.load(arquivo)

    # A ordem respeita as chaves estrangeiras: alunos antes de usuarios/notas etc.
    ordem = ["alunos", "usuarios", "notas", "faltas", "provas",
             "observacoes", "config", "anotacoes", "historico_chat", "conversas_salvas"]
    # Tabelas do arquivo que não estão na lista entram no final (nada se perde)
    ordem += [t for t in dados_salvos if t not in ordem]

    # Tabelas que realmente existem neste banco (evita erro se o arquivo tiver tabela desconhecida)
    tabelas_existentes = {linha[0] for linha in cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}

    total_importado = 0
    for tabela in ordem:
        linhas = dados_salvos.get(tabela) or []
        if not linhas:
            continue
        if tabela not in tabelas_existentes:
            print(f"Aviso: tabela '{tabela}' do arquivo não existe no banco — pulada.")
            continue
        colunas = list(linhas[0].keys())
        sql = (f"INSERT INTO {tabela} ({', '.join(colunas)}) "
               f"VALUES ({', '.join('?' for _ in colunas)})")
        cursor.executemany(sql, [[linha.get(c) for c in colunas] for linha in linhas])
        total_importado += len(linhas)

    print(f"Banco criado com {total_importado} registros reais vindos de {ARQUIVO_DADOS}.")
else:
    # Aluno precisa existir antes do usuário que aponta para ele (chave estrangeira)
    cursor.execute("INSERT OR IGNORE INTO alunos VALUES (1, 'André')")
    cursor.execute("INSERT OR IGNORE INTO alunos VALUES (2, 'Diego')")
    cursor.execute("INSERT OR IGNORE INTO alunos VALUES (3, 'Tiago')")

    # Logins do sistema (senha vira hash na hora de gravar)
    cursor.executemany(
        "INSERT INTO usuarios (username, senha, tipo, aluno_id) VALUES (?,?,?,?)",
        [
            ("professor1", generate_password_hash("senha123"), "professor", None),  # professor não tem aluno vinculado
            ("2612388", generate_password_hash("senha123"), "aluno", 1), # matrícula do André (aluno_id 1)
            ("2610725", generate_password_hash("senha123"), "aluno", 2), # matrícula do Diego (aluno_id 2)
            ("Tiago", generate_password_hash("senha123"), "aluno", 3), # login do aluno Tiago (aluno_id 3)
        ]
    )

    # Notas de teste
    cursor.executemany("INSERT INTO notas (aluno_id, materia, nota) VALUES (?,?,?)", [
        (1, "Engenharia de Dados", 7.5),
        (1, "Engenharia de Dados", 8.0),
        (1, "Engenharia de Dados", 5.5),
        (1, "Engenharia de Soluções", 8.0),
        (1, "Engenharia de Soluções", 7.8),
        (1, "Engenharia de Soluções", 6.2),
        (1, "Fundamentos da Computação e Infraestrutura", 5.5),
        (1, "Fundamentos da Computação e Infraestrutura", 6.3),
        (1, "Fundamentos da Computação e Infraestrutura", 9.0),
    ])

    cursor.executemany("INSERT OR IGNORE INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?,?,?,?)", [
        (1, "Engenharia de Dados", 4, 40),
        (1, "Engenharia de Soluções", 2, 40),
        (1, "Fundamentos da Computação e Infraestrutura", 12, 40),
    ])

    cursor.executemany("INSERT OR IGNORE INTO provas (aluno_id, materia, data, conteudo) VALUES (?,?,?,?)", [
        # Dia 09/06/2026: prova ÚNICA cobrindo todas as matérias (uma só, não uma por matéria)
        (1, "Todas as matérias", "2026-06-09", "Prova única cobrindo as 5 matérias: Engenharia de Dados (modelagem de dados, SQL e ETL); Engenharia de Soluções (lógica de programação em Python); Fundamentos da Computação e Infraestrutura (arquitetura de computadores, sistemas operacionais e redes); Cidadania, Ética e Espiritualidade; e Fundamentos Matemáticos para a Computação."),
        # Apresentação do projeto: 15/06/2026 (as férias começam no dia 16)
        (1, "Projeto Integrador", "2026-06-15", "Apresentação final do projeto"),
    ])

    # Diego (2) e Tiago (3): mesmas matérias do André (colunas iguais), mas notas/faltas próprias (linhas diferentes)
    cursor.executemany("INSERT INTO notas (aluno_id, materia, nota) VALUES (?,?,?)", [
        # Diego (2) - aluno com bom desempenho
        (2, "Engenharia de Dados", 6.0),
        (2, "Engenharia de Dados", 7.5),
        (2, "Engenharia de Dados", 8.0),
        (2, "Engenharia de Soluções", 9.0),
        (2, "Engenharia de Soluções", 8.0),
        (2, "Engenharia de Soluções", 9.5),
        (2, "Fundamentos da Computação e Infraestrutura", 5.0),
        (2, "Fundamentos da Computação e Infraestrutura", 6.0),
        (2, "Fundamentos da Computação e Infraestrutura", 7.0),
        # Tiago (3) - aluno em situação de risco
        (3, "Engenharia de Dados", 4.0),
        (3, "Engenharia de Dados", 5.5),
        (3, "Engenharia de Dados", 6.0),
        (3, "Engenharia de Soluções", 7.0),
        (3, "Engenharia de Soluções", 6.5),
        (3, "Engenharia de Soluções", 8.0),
        (3, "Fundamentos da Computação e Infraestrutura", 3.0),
        (3, "Fundamentos da Computação e Infraestrutura", 5.0),
        (3, "Fundamentos da Computação e Infraestrutura", 4.5),
    ])

    cursor.executemany("INSERT OR IGNORE INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?,?,?,?)", [
        (2, "Engenharia de Dados", 6, 40),
        (2, "Engenharia de Soluções", 2, 40),
        (2, "Fundamentos da Computação e Infraestrutura", 8, 40),
        (3, "Engenharia de Dados", 11, 40), # acima de 25% -> reprovado por falta
        (3, "Engenharia de Soluções", 4, 40),
        (3, "Fundamentos da Computação e Infraestrutura", 12, 40),  # acima de 25% -> reprovado por falta
    ])

    # Provas são as mesmas para a turma toda (mesma data e conteúdo), só mudam de dono
    for novo_id in (2, 3):
        cursor.execute("INSERT OR IGNORE INTO provas (aluno_id, materia, data, conteudo) SELECT ?, materia, data, conteudo FROM provas WHERE aluno_id = 1", (novo_id,))

    # ── Matérias novas: Cidadania, Ética e Espiritualidade + Fundamentos Matemáticos para a Computação ──
    # Mesmas duas matérias para todos os alunos (colunas iguais), com notas próprias de cada um (linhas diferentes)
    cursor.executemany("INSERT INTO notas (aluno_id, materia, nota) VALUES (?,?,?)", [
        # André (1) - desempenho mediano
        (1, "Cidadania, Ética e Espiritualidade", 7.0),
        (1, "Cidadania, Ética e Espiritualidade", 8.5),
        (1, "Cidadania, Ética e Espiritualidade", 6.5),
        (1, "Fundamentos Matemáticos para a Computação", 6.0),
        (1, "Fundamentos Matemáticos para a Computação", 5.5),
        (1, "Fundamentos Matemáticos para a Computação", 7.0),
        # Diego (2) - bom desempenho
        (2, "Cidadania, Ética e Espiritualidade", 8.5),
        (2, "Cidadania, Ética e Espiritualidade", 9.0),
        (2, "Cidadania, Ética e Espiritualidade", 8.0),
        (2, "Fundamentos Matemáticos para a Computação", 7.0),
        (2, "Fundamentos Matemáticos para a Computação", 6.5),
        (2, "Fundamentos Matemáticos para a Computação", 8.0),
        # Tiago (3) - em situação de risco
        (3, "Cidadania, Ética e Espiritualidade", 5.0),
        (3, "Cidadania, Ética e Espiritualidade", 4.0),
        (3, "Cidadania, Ética e Espiritualidade", 6.0),
        (3, "Fundamentos Matemáticos para a Computação", 3.5),
        (3, "Fundamentos Matemáticos para a Computação", 4.0),
        (3, "Fundamentos Matemáticos para a Computação", 5.0),
    ])

    cursor.executemany("INSERT OR IGNORE INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?,?,?,?)", [
        (1, "Cidadania, Ética e Espiritualidade", 3, 40),
        (1, "Fundamentos Matemáticos para a Computação", 5, 40),
        (2, "Cidadania, Ética e Espiritualidade", 1, 40),
        (2, "Fundamentos Matemáticos para a Computação", 4, 40),
        (3, "Cidadania, Ética e Espiritualidade", 9, 40),
        (3, "Fundamentos Matemáticos para a Computação", 13, 40),
    ])

    # ── 10 alunos extras (mesmo padrão: 5 matérias, 3 notas cada, faltas e as provas do aluno 1) ──
    # 7 com perfil regular (notas 6.5–9.5, poucas faltas) e 3 com um fator de risco.
    # Junto com os originais (Diego regular; André e Tiago em risco) dá 8 regulares / 5 em risco (~60%).
    random.seed(2026)  # seed fixa: gera sempre os mesmos dados
    materias_5 = [
        "Engenharia de Dados",
        "Engenharia de Soluções",
        "Fundamentos da Computação e Infraestrutura",
        "Cidadania, Ética e Espiritualidade",
        "Fundamentos Matemáticos para a Computação",
    ]
    nomes_extras = ["Ana Souza", "Bruno Lima", "Carla Mendes", "Daniel Rocha", "Eduarda Alves",
                    "Felipe Castro", "Gabriela Dias", "Henrique Nunes", "Isabela Pinto", "João Vitor"]
    indices_em_risco = {3, 6, 9}  # quais dos 10 extras ficam em risco (Daniel, Gabriela, João)
    for i, nome in enumerate(nomes_extras):
        matricula = str(2612401 + i)
        cursor.execute("INSERT INTO alunos (nome) VALUES (?)", (nome,))
        aid = cursor.lastrowid
        cursor.execute("INSERT INTO usuarios (username, senha, tipo, aluno_id) VALUES (?, ?, 'aluno', ?)",
                       (matricula, generate_password_hash("senha123"), aid))
        for mat in materias_5:
            for _ in range(3):
                cursor.execute("INSERT INTO notas (aluno_id, materia, nota) VALUES (?, ?, ?)",
                               (aid, mat, round(random.uniform(6.5, 9.5), 1)))  # notas boas (>= corte)
            cursor.execute("INSERT OR IGNORE INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?, ?, ?, 40)",
                           (aid, mat, random.randint(0, 8)))  # poucas faltas (<= 25%)
        if i in indices_em_risco:
            # injeta um fator de risco: uma matéria com faltas acima de 25% (reprovado por falta)
            mat_risco = materias_5[random.randint(0, 4)]
            cursor.execute("UPDATE faltas SET faltas = 13 WHERE aluno_id = ? AND materia = ?", (aid, mat_risco))
        # mesmas provas do André (aluno 1)
        cursor.execute("INSERT OR IGNORE INTO provas (aluno_id, materia, data, conteudo) "
                       "SELECT ?, materia, data, conteudo FROM provas WHERE aluno_id = 1", (aid,))

    print("Banco criado e populado com os dados de exemplo.")

conn.commit()
conn.close()
