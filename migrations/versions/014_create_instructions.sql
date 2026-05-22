-- Create instruction categories and instructions tables
CREATE TABLE IF NOT EXISTS instruction_categories (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS instructions (
    id SERIAL PRIMARY KEY,
    category_id INTEGER REFERENCES instruction_categories(id) ON DELETE SET NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    created_by VARCHAR(255),
    updated_by VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE
);

-- Seed default category and instruction if not present
INSERT INTO instruction_categories (name)
SELECT 'Navodila za uporabo aplikacije Deklaracije'
WHERE NOT EXISTS (
    SELECT 1 FROM instruction_categories WHERE name = 'Navodila za uporabo aplikacije Deklaracije'
);

INSERT INTO instructions (category_id, title, content, created_by)
SELECT c.id,
       'Kako uporabljati aplikacijo Deklaracije (osnovni koraki)',
       $$
       Namen aplikacije Deklaracije
       ---------------------------------
       Aplikacija je namenjena pripravi, urejanju in pošiljanju varnostnih deklaracij za parfume ter osnovnemu upravljanju zalog in serij. Povezana je s Shopify trgovino, kar omogoča hiter pregled naročil in avtomatizacijo delovnih korakov.

       1) Prijava in dovoljenja
       - Prijavite se s svojim uporabniškim računom. Dostop do zavihkov in funkcij je odvisen od vaših dovoljenj.
       - Administrator lahko ureja dovoljenja v zavihku Uporabniki (kdo lahko gleda/ureja parfume, serije, naročila, pošilja e‑pošto, vidi globalne akcije ...).

       2) Naročila
       - Zavihek Naročila prikazuje zadnja naročila iz Shopify.
       - Klik na naročilo odpre podrobnosti: osnovni podatki, slike (nalaganje/ogled), status in možnost ponovnega pošiljanja deklaracije.
       - Dodajanje slik: uporabite gumb za nalaganje. Slike lahko briše le lastnik ali uporabnik z dodatnim dovoljenjem za brisanje vseh slik.

       3) Vnos & Zaloga (Katalog)
       - Izberite proizvajalca in parfum za pregled ali urejanje.
       - Podprta polja: INCI sestava, status na zalogi, vklop/izklop sinhronizacije s Shopify.
       - Serije: dodajajte/urejajte serije (rok uporabe, serijska številka, datum odprtja, ali je tester). Posebna pravila veljajo za MISTRAL (brez serijske) in FLORGARDEN (obvezna serijska v posebnem formatu YY/AAAAA BBB/DDMM).
       - Audit sledi: pri urejanju serije se zabeleži kdo in kdaj je urejal (Uredil / Urejeno v tabeli serij).

       4) Opozorila
       - Prikazuje izdelke z bližajočim se rokom uporabe. Klik na opozorilo odpre urejanje serij za izbrani parfum (če imate dovoljenje za serije).

       5) Globalne akcije
       - Na voljo glede na dovoljenja: sinhronizacija s Shopify (zaloga/INCI), ročno pošiljanje deklaracij, ustvarjanje PDF‑jev za tisk.
       - Vklop “testnega e‑poštnega načina” pošilja deklaracije na administratorski e‑poštni naslov.

       6) Ročno pošiljanje & Tisk
       - Izberite parfume in ustvarite PDF deklaracijo ali pošljite e‑pošto.
       - Predloge e‑pošte samodejno vključijo logotip in potrebne podatke.

       7) Slike naročil
       - Naložite slike (etikete, dokumenti) neposredno v naročilu.
       - Klik na sliko za večji ogled. Brisanje: le lastnik ali uporabnik z dodatnim dovoljenjem za brisanje vseh slik.

       8) Najpogostejše težave
       - Stran se ne osveži pravilno: uporabite Ctrl/Cmd+Shift+R.
       - Slike se ne naložijo: preverite velikost datoteke in povezavo.
       - Napake ali nejasnosti: kontaktirajte administratorja.
       $$,
       'admin'
FROM instruction_categories c
WHERE c.name = 'Navodila za uporabo aplikacije Deklaracije'
  AND NOT EXISTS (
      SELECT 1 FROM instructions i WHERE i.category_id = c.id
  );


