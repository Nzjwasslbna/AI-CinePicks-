# -*- coding: utf-8 -*-
"""Unit test untuk MovieEngine: pencarian, intent, reasoning, dan pengambilan keputusan."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import MovieEngine, tokenize, normalize  # noqa: E402


class TestEngineBasics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MovieEngine()

    def test_dataset_loaded(self):
        self.assertGreater(len(self.engine.movies), 9000)
        self.assertGreater(len(self.engine.postings), 10000)

    def test_tokenize_removes_stopwords(self):
        toks = tokenize("film action terbaik")
        self.assertNotIn("film", toks)
        self.assertIn("action", toks)

    def test_normalize(self):
        self.assertEqual(normalize("Spider-Man: No Way Home"), "spidermannowayhome")

    def test_find_title_exact(self):
        m, score = self.engine.find_title("Interstellar")
        self.assertIsNotNone(m)
        self.assertEqual(m.title, "Interstellar")
        self.assertGreater(score, 0.5)

    def test_find_title_guard_short_query(self):
        # "film zombie" boleh cocok dengan judul "Zombie", tetapi TIDAK boleh
        # salah mencocokkan "G-Zombie" (guard fuzzy untuk query lebih panjang dari judul).
        m, _ = self.engine.find_title("film zombie")
        if m is not None:
            self.assertNotEqual(m.title, "G-Zombie")

    def test_find_title_partial(self):
        # "endgame" harus cocok dengan "Avengers: Endgame"
        m, _ = self.engine.find_title("endgame")
        self.assertIsNotNone(m)
        self.assertEqual(m.title, "Avengers: Endgame")

    def test_find_title_ocr_noisy(self):
        # Teks OCR berisik yang hanya memuat kata ENDGAME
        noise = "i~ N ,',@\\\\ > AN W 2\\\\ S50 NS = 4 T W X N Gl %\\\\/ P el 7ag % 2 &3 2 A B W N \" [~ ENDGAME"
        m, score = self.engine.find_title_ocr(noise)
        self.assertIsNotNone(m)
        self.assertEqual(m.title, "Avengers: Endgame")
        self.assertGreater(score, 0.5)

    def test_find_title_embedded_in_long_text(self):
        # Judul lengkap di dalam teks panjang (mis. poster dengan teks tambahan)
        m, _ = self.engine.find_title("MARVEL STUDIOS AVENGERS ENDGAME APRIL 26")
        self.assertIsNotNone(m)
        self.assertEqual(m.title, "Avengers: Endgame")


class TestIntents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = MovieEngine()

    def test_chat_pendidikan_not_action(self):
        r = self.engine.chat("rekomendasi film pendidikan")
        self.assertEqual(r["lang"], "id")
        self.assertTrue(r["movies"])
        top = [m["title"] for m in r["movies"][:3]]
        self.assertNotIn("The Dark Knight", top)
        self.assertNotIn("Spider-Man: No Way Home", top)

    def test_chat_country_indonesia(self):
        r = self.engine.chat("rekomendasi film indonesia")
        self.assertEqual(r["lang"], "id")
        self.assertTrue(r["movies"])
        self.assertIn("Indonesia", r["reply"])
        self.assertIn("Indonesia", r["movies"][0].get("reason", ""))

    def test_chat_zombie_genre_horror(self):
        r = self.engine.chat("film zombie")
        self.assertTrue(r["movies"])
        genres = r["movies"][0].get("genres", [])
        self.assertIn("Horror", genres)

    def test_chat_anak_family(self):
        r = self.engine.chat("rekomendasi film anak")
        self.assertTrue(r["movies"])
        self.assertTrue(any("Family" in m.get("genres", []) or "Animation" in m.get("genres", [])
                            for m in r["movies"][:3]))

    def test_chat_superhero_action(self):
        r = self.engine.chat("film super hero")
        self.assertTrue(r["movies"])
        genres = r["movies"][0].get("genres", [])
        self.assertTrue("Action" in genres or "Adventure" in genres)
        titles = [m["title"] for m in r["movies"][:3]]
        self.assertFalse(any("LEGO" in t for t in titles))

    def test_chat_similar(self):
        r = self.engine.chat("mirip Interstellar")
        self.assertIn("Interstellar", r["reply"])
        self.assertTrue(r["movies"])

    def test_chat_semantic_no_result(self):
        r = self.engine.chat("zzzqqqxxx")
        self.assertEqual(r["movies"], [])

    def test_chat_surprise(self):
        r = self.engine.chat("surprise me")
        self.assertEqual(len(r["movies"]), 5)

    def test_chat_trending(self):
        r = self.engine.chat("film populer")
        self.assertTrue(r["movies"])

    def test_chat_page_pagination(self):
        r0 = self.engine.chat("film action", page=0)
        r1 = self.engine.chat("film action", page=1)
        self.assertTrue(r0["movies"] and r1["movies"])
        self.assertNotEqual(r0["movies"][0]["title"], r1["movies"][0]["title"])

    def test_chat_year_filter(self):
        r = self.engine.chat("film horor tahun 2022")
        self.assertTrue(r["movies"])
        self.assertTrue(all(m["year"] == 2022 for m in r["movies"]))




class TestRefinementMultiTurn(unittest.TestCase):
    """Multi-turn: penghalusan pencarian (tahun, rating, pengecualian genre, negara, reset)."""

    @classmethod
    def setUpClass(cls):
        cls.engine = MovieEngine()

    def test_parse_year_up(self):
        self.assertEqual(self.engine.parse_refinement("yang tahun 2020 ke atas"), {"year_min": 2020})

    def test_parse_year_down_and_decade(self):
        self.assertEqual(self.engine.parse_refinement("sebelum 2000"), {"year_max": 1999})
        d = self.engine.parse_refinement("tahun 90an")
        self.assertEqual((d["year_min"], d["year_max"]), (1990, 1999))

    def test_parse_rating_and_exclude(self):
        self.assertEqual(self.engine.parse_refinement("rating di atas 8"), {"min_rating": 8.0})
        self.assertEqual(self.engine.parse_refinement("tanpa horor"), {"exclude_genres": ["Horror"]})
        d = self.engine.parse_refinement("bukan animasi dan komedi")
        self.assertEqual(set(d["exclude_genres"]), {"Animation", "Comedy"})

    def test_fresh_queries_are_not_refinements(self):
        for q in ("film korea", "horor tahun 2022", "film anak", "film populer",
                  "Interstellar", "lagi", "yang lain", "tambah lagi", "surprise me"):
            self.assertIsNone(self.engine.parse_refinement(q), q)

    def test_reset(self):
        self.assertEqual(self.engine.parse_refinement("reset filter"), {"reset": True})
        self.assertEqual(self.engine.merge_ctx({"min_rating": 8}, {"reset": True}), {})

    def test_merge_ctx_is_cumulative(self):
        ctx = self.engine.merge_ctx({}, {"year_min": 2020})
        ctx = self.engine.merge_ctx(ctx, {"min_rating": 7.5})
        ctx = self.engine.merge_ctx(ctx, {"exclude_genres": ["Horror"]})
        self.assertEqual(ctx, {"year_min": 2020, "min_rating": 7.5, "exclude_genres": ["Horror"]})
        # genre yang dikecualikan lalu ditambahkan kembali harus keluar dari daftar pengecualian
        ctx = self.engine.merge_ctx(ctx, {"add_genres": ["Horror"]})
        self.assertNotIn("Horror", ctx.get("exclude_genres", []))

    def test_merge_year_exact_clears_range(self):
        ctx = self.engine.merge_ctx({}, {"year_min": 1990, "year_max": 1999})
        ctx = self.engine.merge_ctx(ctx, {"year": 2022})
        self.assertEqual(ctx, {"year": 2022})

    def test_chat_with_filters_respected(self):
        ctx = {"year_min": 2015, "min_rating": 7.5, "exclude_genres": ["Animation"]}
        res = self.engine.chat("film action terbaik", ctx=ctx)
        self.assertTrue(res["movies"])
        for m in res["movies"]:
            self.assertGreaterEqual(m["year"], 2015)
            self.assertGreaterEqual(m["rating"], 7.5)
            self.assertNotIn("Animation", m["genres"])

    def test_chat_filters_apply_to_similar_and_title(self):
        for q in ("mirip Interstellar", "Interstellar"):
            res = self.engine.chat(q, ctx={"year_min": 2010})
            self.assertTrue(res["movies"], q)
            for m in res["movies"]:
                self.assertGreaterEqual(m["year"], 2010, q)

    def test_chat_added_country_and_genre(self):
        res = self.engine.chat("film action terbaik", ctx={"countries": ["ko"]})
        self.assertTrue(res["movies"])

    def test_impossible_filter_returns_empty(self):
        res = self.engine.chat("film action terbaik", ctx={"min_rating": 10, "year_min": 2100})
        self.assertEqual(res["movies"], [])

    def test_about_mode_pagination_advances(self):
        # Bug lama: halaman berikutnya untuk judul tunggal selalu mengulang hasil yang sama.
        a = [m["title"] for m in self.engine.chat("Interstellar", page=0)["movies"]]
        b = [m["title"] for m in self.engine.chat("Interstellar", page=1)["movies"]]
        self.assertTrue(a and b)
        self.assertFalse(set(a) & set(b))

    def test_describe_delta(self):
        parts = self.engine.describe_delta({"min_rating": 8.0, "exclude_genres": ["Horror"]}, "id")
        self.assertIn("tanpa Horror", parts)
        self.assertIn("rating ≥ 8", parts)


if __name__ == "__main__":
    unittest.main()
