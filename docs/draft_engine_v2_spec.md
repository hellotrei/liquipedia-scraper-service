# Draft Engine v2 (Role Fleksibel) - Technical Specification

## 1. Tujuan

Membangun engine rekomendasi draft yang realistis untuk skenario tournament/ranked Mobile Legends:

- Urutan pick tidak dikunci per role (tidak wajib exp -> jungle -> mid -> gold -> roam).
- Hero bisa memiliki lebih dari satu role (flex pick).
- Rekomendasi tetap relevan berdasarkan:
  - tier/meta power,
  - counter lawan,
  - sinergi tim,
  - kelayakan komposisi role akhir.

Output akhir engine harus bisa digunakan oleh UI Draft Master yang sudah ada tanpa mengubah alur user secara drastis.

## 2. Masalah pada Engine v1

Engine v1 mengasumsikan pick selalu mengisi role berikutnya di role order tetap. Akibatnya:

- Tidak realistis untuk drafting kompetitif.
- Hero flex tidak bisa dimanfaatkan optimal.
- Rekomendasi bisa salah konteks ketika strategi tim menunda role tertentu.

## 3. Prinsip Desain Engine v2

1. Pick bersifat `role-agnostic`.
2. Assignment role dilakukan dinamis setiap perubahan state.
3. Validitas komposisi role tim menjadi constraint utama.
4. Rekomendasi berorientasi fase draft (early/mid/late).
5. Semua hasil rekomendasi wajib punya alasan (explainability).

## 4. Data Contract Baru

## 4.1 Hero Role Pool

File baru (sumber ground truth role fleksibel):

`apps/scraper-service/hero_role_pool.json`

Contoh schema:

```json
{
  "version": "2026-02-21",
  "roles": ["exp_lane", "jungle", "mid_lane", "gold_lane", "roam"],
  "heroes": {
    "suyou": {
      "possibleRoles": ["exp_lane", "jungle"],
      "rolePower": {
        "exp_lane": 0.86,
        "jungle": 0.77
      },
      "tags": ["flex", "frontline"]
    },
    "x_borg": {
      "possibleRoles": ["exp_lane", "gold_lane"],
      "rolePower": {
        "exp_lane": 0.88,
        "gold_lane": 0.69
      },
      "tags": ["flex", "sustain"]
    }
  }
}
```

Catatan:

- `possibleRoles` wajib minimal 1 role.
- `rolePower` skala `0..1` dan dipakai saat role assignment.
- Data awal boleh semi-manual, lalu ditingkatkan otomatis dari statistik match.

## 4.2 Draft State (runtime)

```json
{
  "patch": "M7",
  "sequenceKey": "mlbb_standard_bo5",
  "turnIndex": 6,
  "actionProgress": 0,
  "picks": {
    "ally": ["joy", "suyou"],
    "enemy": ["fanny", "kalea"]
  },
  "bans": {
    "ally": ["hylos", "granger"],
    "enemy": ["harith", "gloo"]
  }
}
```

Penting:

- Picks disimpan sebagai daftar hero tanpa role fix.
- Assignment role final dihitung oleh optimizer.

## 4.3 Recommendation Response

```json
{
  "mode": "pick",
  "side": "ally",
  "turn": { "index": 6, "text": "Ally pick 2 heroes", "remaining": 2 },
  "composition": {
    "ally": {
      "isFeasible": true,
      "bestAssignment": {
        "exp_lane": "suyou",
        "jungle": "joy"
      },
      "openRoles": ["mid_lane", "gold_lane", "roam"],
      "feasibilityScore": 0.91
    },
    "enemy": {
      "isFeasible": true,
      "bestAssignment": {
        "jungle": "fanny",
        "roam": "kalea"
      },
      "openRoles": ["exp_lane", "mid_lane", "gold_lane"],
      "feasibilityScore": 0.88
    }
  },
  "recommendations": [
    {
      "hero": "pharsa",
      "score": 82.4,
      "tier": "SS",
      "predictedRoles": ["mid_lane"],
      "components": {
        "meta": 31.2,
        "counter": 18.9,
        "synergy": 12.5,
        "deny": 8.8,
        "flex": 2.0,
        "feasibility": 9.0
      },
      "reasons": [
        "Counter kuat vs 2 hero lawan",
        "Menutup gap role mid lane",
        "Win rate tinggi pada data M7"
      ]
    }
  ]
}
```

## 5. Formula Scoring

## 5.1 Komponen

Gunakan skor ter-normalisasi `0..100`:

- `meta_score`: tier + pickWin + pickCount + banCount.
- `counter_score`: dampak terhadap hero lawan yang sudah dipick.
- `synergy_score`: kecocokan dengan hero ally yang sudah dipick.
- `deny_score`: nilai jika hero tersebut kuat untuk side lawan.
- `flex_score`: bonus hero dengan banyak role (lebih tinggi di early phase).
- `feasibility_score`: bonus jika pick menjaga peluang komposisi 5 role unik.

## 5.2 Bobot Dinamis per Fase

Gunakan bobot berbeda sesuai fase pick side aktif:

- Early (pick ke-1 sampai ke-2):
  - meta 0.34, counter 0.16, synergy 0.12, deny 0.18, flex 0.12, feasibility 0.08
- Mid (pick ke-3 sampai ke-4):
  - meta 0.28, counter 0.26, synergy 0.18, deny 0.12, flex 0.06, feasibility 0.10
- Late (pick ke-5):
  - meta 0.20, counter 0.36, synergy 0.20, deny 0.08, flex 0.02, feasibility 0.14

Final:

`final_score = sum(weight_i * component_i)`

## 6. Role Assignment Optimizer

## 6.1 Problem Formulation

Untuk setiap tim, cari mapping hero -> role dengan constraint:

- Satu hero satu role.
- Satu role maksimal satu hero.
- Role hero harus ada di `possibleRoles`.

Tujuan:

- Memaksimalkan total `rolePower(hero, role)`.

## 6.2 Solusi

Karena skala kecil (maks 5 hero), gunakan salah satu:

1. Enumerasi semua assignment valid (permutasi kecil).
2. Atau Hungarian / max-weight bipartite matching.

Rekomendasi implementasi awal: enumerasi karena lebih sederhana dan cukup cepat.

## 6.3 Output Optimizer

- `isFeasible`: apakah assignment 5 role unik masih mungkin dicapai.
- `bestAssignment`: mapping role terbaik saat ini.
- `openRoles`: role yang belum terisi pada best assignment.
- `feasibilityScore`: metrik 0..1 (semakin tinggi semakin aman).

## 7. Lookahead (Beam Search)

Agar rekomendasi tidak myopic, lakukan simulasi singkat:

- Kedalaman: 2 ply (aksi saat ini + respons lawan).
- Beam width: 6 (ambil kandidat atas tiap langkah).

Pseudo:

```text
candidates = top_k_by_base_score(current_state)
for hero in candidates:
  s1 = apply(current_state, hero)
  enemy_best = top_m_enemy_responses(s1)
  value(hero) = immediate_score(s1) - avg(enemy_best)
return top_n(value)
```

Catatan:

- Aktifkan lookahead hanya untuk PICK.
- Untuk BAN cukup 1-step scoring agar latensi tetap rendah.

## 8. Endpoint Plan (Scraper Service)

Tambahkan endpoint baru agar UI bisa migrate bertahap:

1. `POST /api/draft/v2/recommend`
   - Input: draft state.
   - Output: rekomendasi pick/ban + explainability.

2. `POST /api/draft/v2/analyze`
   - Input: full draft state (5 pick vs 5 pick).
   - Output: prediksi matchup + breakdown komponen.

3. `POST /api/draft/v2/assign`
   - Input: daftar hero tim.
   - Output: assignment role terbaik + feasible flag.

4. `GET /api/draft/v2/meta`
   - Output: versi data, bobot scoring, sequence key.

Endpoint lama tetap berjalan selama migrasi.

## 9. Step Implementasi (Sebelum Ubah Engine UI)

## Phase 0 - Baseline dan Safety

1. Freeze engine sekarang sebagai `draft_engine_v1`.
2. Tambahkan feature flag UI: `engine=v1|v2`.
3. Tambahkan snapshot test output v1 untuk regression guard.

## Phase 1 - Data Layer

1. Buat `hero_role_pool.json` initial seed.
2. Tambahkan loader + validator schema.
3. Tambahkan override file untuk cepat update patch/meta.

## Phase 2 - Core Engine v2 (Backend)

1. Implement `role_assignment_optimizer.py`.
2. Implement `draft_scorer_v2.py`.
3. Implement `lookahead.py`.
4. Tambahkan endpoint `/api/draft/v2/*`.

## Phase 3 - Explainability

1. Semua recommendation wajib return:
   - komponen skor,
   - alasan top 2-3,
   - predicted roles.
2. Tambahkan debug mode (`?debug=true`) untuk detail internal.

## Phase 4 - UI Integrasi

1. Saat pick, UI panggil `/api/draft/v2/recommend`.
2. Slot role di UI menjadi "proyeksi" dari assignment, bukan lock urutan.
3. Tampilkan badge `flex` jika hero multi-role.
4. Tampilkan warning jika `isFeasible=false`.

## Phase 5 - Validasi

1. Uji 30 skenario draft historis.
2. Bandingkan v1 vs v2:
   - kualitas rekomendasi,
   - konsistensi role,
   - kepuasan user.
3. Jika stabil, set v2 sebagai default.

## 10. Acceptance Criteria

Sebuah build v2 dianggap siap jika:

1. Hero flex bisa dipick kapan pun tanpa memaksa role order.
2. Sistem selalu bisa menjelaskan kenapa hero direkomendasikan.
3. Tidak ada rekomendasi yang menyebabkan dead-end role tanpa warning.
4. Latensi endpoint rekomendasi <= 250ms (tanpa cache berat) pada state normal.
5. UI tetap nyaman dipakai dan tidak menambah langkah user.

## 11. Risiko dan Mitigasi

1. Data role pool tidak akurat.
   - Mitigasi: override file + versioning + review cepat per patch.

2. Formula terlalu overfit ke data M7.
   - Mitigasi: normalisasi + cap komponen + A/B test.

3. Latensi naik karena lookahead.
   - Mitigasi: beam width kecil, memoization state hash.

4. Kebingungan user karena role assignment dinamis.
   - Mitigasi: tampilkan "Predicted Role" per hero di UI.

## 12. Implementasi Pertama yang Disarankan (MVP v2)

Agar cepat jalan, MVP v2 cukup:

1. Role pool + optimizer + scoring tanpa lookahead.
2. Endpoint `/api/draft/v2/recommend` saja.
3. UI toggle `Gunakan Engine v2`.
4. Setelah stabil, baru tambah lookahead dan endpoint analyze v2 penuh.
