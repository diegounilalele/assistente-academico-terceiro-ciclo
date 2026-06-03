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
cursor.execute("INSERT OR IGNORE INTO alunos VALUES (1, 'Carlos')")

# Logins do sistema (senha vira hash na hora de gravar)
cursor.executemany(
    "INSERT INTO usuarios (username, senha, tipo, aluno_id) VALUES (?,?,?,?)",
    [
        ("professor1", generate_password_hash("senha123"), "professor", None),  # professor não tem aluno vinculado
        ("carlos",     generate_password_hash("senha123"), "aluno", 1),         # login do aluno Carlos (id 1)
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
    (1, "Engenharia de Dados", "2025-06-10", "Equações do 2º grau e funções"),
    (1, "Engenharia de Soluções", "2025-06-12", "Interpretação de texto e gramática"),
    (1, "Fundamentos da Computação e Infraestrutura", "2025-06-15", "Segunda Guerra Mundial"),
])

conn.commit()
conn.close()
print("Banco criado ou atualizado com sucesso")
