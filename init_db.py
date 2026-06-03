import sqlite3

def init_db():
    conn = sqlite3.connect('citations.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS citations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL UNIQUE,             -- Enforce unique titles to prevent duplicate alerts
        system TEXT CHECK(system IN ('Delta', 'DeltaAI', 'Unknown')),
        alert_trigger TEXT,                     -- The specific trigger keyword phrase that generated the alert
        status TEXT DEFAULT 'Pending' CHECK(status IN ('Pending', 'Verified', 'Rejected')),
        reasoning TEXT,                         -- Local LLM's logic for accepting/rejecting the paper
        usage_context TEXT,                     -- The text snippet/quote showing how Delta/DeltaAI was mentioned
        uiuc_affiliated INTEGER DEFAULT 0,      -- Boolean flag: 1 if UIUC authors are found, 0 otherwise
        uiuc_authors_depts TEXT,                -- String or JSON block listing UIUC author names & departments
        award_number TEXT,                      -- Extracted NSF Grant ID (OAC-2005572 or OAC-2320345)
        doi_or_url TEXT,                        -- DOI link or publication/arXiv source URL
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    
    conn.commit()
    conn.close()
    print("Database 'citations.db' initialized with schema.")

if __name__ == "__main__":
    init_db()
