import sqlite3
from werkzeug.security import generate_password_hash  # transforma a senha em hash (vem junto do Flask)

conn = sqlite3.connect("universidade.db")
cursor = conn.cursor()

# Ativa o suporte a chaves estrangeiras (ON DELETE CASCADE)
cursor.execute("PRAGMA foreign_keys = ON;")

cursor.executescript("""
    DROP TABLE IF EXISTS notas;
    DROP TABLE IF EXISTS usuarios;
    DROP TABLE IF EXISTS faltas;
    DROP TABLE IF EXISTS provas;

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

    -- Login do sistema. A senha é guardada como HASH, nunca em texto puro.
    -- aluno_id liga um login de aluno ao seu registro na tabela alunos (NULL para professor).
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        senha TEXT,
        tipo TEXT,            -- 'professor' ou 'aluno'
        aluno_id INTEGER,
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

    CREATE TABLE IF NOT EXISTS historico (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        aluno_id INTEGER,
        role TEXT,
        conteudo TEXT,
        data_hora DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (aluno_id) REFERENCES alunos(id) ON DELETE CASCADE
    );
""")

# Aluno precisa existir antes do usuário que aponta para ele (chave estrangeira)
cursor.execute("INSERT OR IGNORE INTO alunos VALUES (1, 'André')")
cursor.execute("INSERT OR IGNORE INTO alunos VALUES (2, 'Diego')")
cursor.execute("INSERT OR IGNORE INTO alunos VALUES (3, 'Tiago')")

# Logins do sistema (senha vira hash na hora de gravar)
cursor.executemany(
    "INSERT INTO usuarios (username, senha, tipo, aluno_id) VALUES (?,?,?,?)",
    [
        ("professor1", generate_password_hash("senha123"), "professor", None),  # professor não tem aluno vinculado
        ("André", generate_password_hash("senha123"), "aluno", 1), # login do aluno André (id 1)
        ("Diego", generate_password_hash("senha123"), "aluno", 2), # login do aluno Diego (id 2)
        ("Tiago", generate_password_hash("senha123"), "aluno", 3), # login do aluno Tiago (id 3)
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
    # Todas as provas no mesmo dia: 09/06/2026
    (1, "Engenharia de Dados", "2026-06-09", "Modelagem de dados, SQL e processos de ETL"),
    (1, "Engenharia de Soluções", "2026-06-09", "Lógica de programação em Python: variáveis, condicionais, laços e funções"),
    (1, "Fundamentos da Computação e Infraestrutura", "2026-06-09", "Arquitetura de computadores, sistemas operacionais e redes"),
    # Apresentação do projeto no dia seguinte: 10/06/2026
    (1, "Projeto Integrador", "2026-06-10", "Apresentação final do projeto"),
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
    (3, "Cidadania, Ética e Espiritualidade", 9, 40),            # 22,5% -> alerta de atenção
    (3, "Fundamentos Matemáticos para a Computação", 13, 40),    # acima de 25% -> reprovado por falta
])

conn.commit()
conn.close()
print("Banco criado ou atualizado com sucesso")
