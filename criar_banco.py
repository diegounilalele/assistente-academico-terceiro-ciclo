import sqlite3

conn = sqlite3.connect("universidade.db")
cursor = conn.cursor()

# ATENÇÃO: Ativa o suporte a chaves estrangeiras no SQLite
cursor.execute("PRAGMA foreign_keys = ON;")

cursor.executescript("""
    DROP TABLE IF EXISTS notas; -- Remove a tabela antiga

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
        tipo TEXT -- se é 'professor' ou 'aluno'
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

# Dados de teste
cursor.execute("INSERT OR IGNORE INTO usuarios (username, senha, tipo) VALUES ('professor1', 'senha123', 'professor')")
cursor.execute("INSERT OR IGNORE INTO alunos VALUES (1, 'Carlos')")

# Inserção de notas simplificada sem o risco de duplicidade de chaves
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
    (1, "Engenharia de Soluções",  2, 40),
    (1, "Fundamentos da Computação e Infraestrutura",   12, 40),
])

cursor.executemany("INSERT OR IGNORE INTO provas (aluno_id, materia, data, conteudo) VALUES (?,?,?,?)", [
    (1, "Engenharia de Dados", "2025-06-10", "Equações do 2º grau e funções"),
    (1, "Engenharia de Soluções",  "2025-06-12", "Interpretação de texto e gramática"),
    (1, "Fundamentos da Computação e Infraestrutura",   "2025-06-15", "Segunda Guerra Mundial"),
])

conn.commit()
conn.close()
print("Banco criado ou atualizado com sucesso")