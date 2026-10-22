"""مطابقة عربية (ar_align): تطبيع، مطابقة تامة ومرنة وتقريبية، مدى المشاهد وحدود القص، جمل التفريغ وتوزيعها على المشاهد."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import ar_align as ar  # noqa: E402


def W(text, a, b):
    return {"text": text, "start": a, "end": b}


# ───────── التطبيع ─────────
def test_norm_removes_diacritics_tatweel_punctuation_and_unifies_letters():
    assert ar.norm("الْعَيْنُ") == "العين" and ar.norm("كـــتاب") == "كتاب" and ar.norm("هٰذا") == "هذا"
    assert ar.norm("أحمد") == ar.norm("احمد") == ar.norm("إحمد") == "احمد"
    assert ar.norm("مدرسة") == "مدرسه" and ar.norm("مؤمن") == "مومن" and ar.norm("شائع") == "شايع" and ar.norm("على") == ar.norm("علي")
    assert ar.norm("٥٠") == ar.norm("۵۰") == "50" and ar.norm("Hello،") == "hello"
    assert ar.norm("؟!،") == "" and ar.norm(None) == "" and ar.norm("  ") == ""


def test_stem_strips_one_prefix_but_keeps_short_words_whole():
    assert ar.stem("والدنيا") == ar.stem("الدنيا") == ar.stem("دنيا") == "دنيا"
    assert ar.stem("بالبيت") == "بيت" and ar.stem("للبيت") == "بيت" and ar.stem("وكتاب") == "كتاب"
    assert ar.stem("ولد") == "ولد" and ar.stem("بيت") == "بيت" and ar.stem("ال") == "ال"


def test_words_of_keeps_punctuation_for_captions():
    assert ar.words_of("ليش عيونك  بتتعب؟\nجرّبي.") == ["ليش", "عيونك", "بتتعب؟", "جرّبي."] and ar.words_of(None) == []


# ───────── المطابقة ─────────
def test_exact_alignment_takes_every_time_from_the_spoken_words():
    script = ar.words_of("ليش عيونك بتتعب آخر النهار")
    asr = [W("ليش", 0.0, 0.3), W("عيونك", 0.35, 0.8), W("بتتعب", 0.85, 1.3), W("آخر", 1.35, 1.7), W("النهار", 1.75, 2.4)]
    r = ar.align(script, asr)
    assert r["coverage"] == 1.0 and r["matched"] == r["total"] == 5
    assert [w["how"] for w in r["words"]] == ["exact"] * 5
    assert [(w["start"], w["end"]) for w in r["words"]] == [(0.0, 0.3), (0.35, 0.8), (0.85, 1.3), (1.35, 1.7), (1.75, 2.4)]
    assert [w["word"] for w in r["words"]] == script                        # الكلمة بتضل كما كتبها المالك


def test_spelling_prefixes_extra_and_missing_words_are_handled():
    script = ar.words_of("ليش عيونك بتتعب آخر النهار ؟ جرّبي القطرة اللطيفة والدنيا حلوة")
    asr = [W("لِيش", 0.0, 0.3), W("عيونك", 0.35, 0.8), W("بتتعب", 0.85, 1.3), W("اخر", 1.35, 1.7), W("النهار", 1.75, 2.4),
           W("يعني", 2.5, 2.8), W("جربي", 3.0, 3.4), W("القطره", 3.45, 3.9), W("دنيا", 4.5, 4.9), W("حلوه", 4.95, 5.3)]
    r = ar.align(script, asr)
    how = {w["word"]: w["how"] for w in r["words"]}
    assert how["والدنيا"] == "flex" and how["اللطيفة"] == "interp" and how["؟"] == "interp" and how["جرّبي"] == "exact"
    assert r["total"] == 10 and r["matched"] == 9 and r["coverage"] == 0.9                 # علامة الترقيم ما بتنعدّ
    lat = next(w for w in r["words"] if w["word"] == "اللطيفة")
    assert 3.9 <= lat["start"] < lat["end"] <= 4.5                                         # موزّعة بين جيرانها
    starts = [w["start"] for w in r["words"]]
    assert starts == sorted(starts)                                                       # الأزمنة بالترتيب


def test_fuzzy_match_catches_small_spelling_differences():
    r = ar.align(["اشتريت", "القطرة"], [W("اشتريتي", 0.0, 0.6), W("القطره", 0.7, 1.2)])
    assert [w["how"] for w in r["words"]] == ["fuzzy", "exact"] and r["coverage"] == 1.0


def test_unmatched_words_are_spread_and_empty_inputs_are_safe():
    r = ar.align(ar.words_of("كلام مختلف تماماً هنا"), [W("شي", 1.0, 1.5), W("تاني", 1.6, 2.0)])
    assert r["coverage"] == 0.0 and all(w["how"] == "interp" for w in r["words"])
    assert r["words"][0]["start"] == 1.0 and r["words"][-1]["end"] <= 2.0 + 1e-9
    assert ar.align([], [W("ا", 0, 1)]) == {"words": [], "coverage": 0.0, "matched": 0, "total": 0}
    r = ar.align(["كلمة"], [], duration=3.0)
    assert r["coverage"] == 0.0 and r["words"][0]["how"] == "interp"


# ───────── مدى المشاهد وحدود القص ─────────
def test_spans_and_cut_points_drop_long_silence_and_never_overlap():
    timing = [W("a", 1.0, 1.4), W("b", 1.5, 2.0), W("c", 2.1, 2.5), W("d", 6.0, 6.5), W("e", 6.6, 7.0)]
    sp = ar.spans(timing, [3, 0, 2])
    assert sp == [(1.0, 2.5), None, (6.0, 7.0)]
    cp = ar.cut_points(sp, 8.0)
    assert cp[1] is None
    (a0, b0), (a2, b2) = cp[0], cp[2]
    assert a0 == 0.8 and b0 == 2.85                              # قبل أول كلمة 0.2ث، وبعد آخر كلمة 0.35ث (الفجوة كبيرة)
    assert a2 == 5.8 and b2 == 7.35 and b0 <= a2                 # الصمت (2.85–5.8) انشال وما في تداخل
    tight = ar.cut_points([(0.0, 1.0), (1.1, 2.0)], 2.0)
    assert tight[0][1] <= tight[1][0] + 1e-9 and tight[0][0] == 0.0 and tight[1][1] == 2.0   # فجوة ضيقة: بتنقسم بالنص
    assert ar.cut_points([None, None], 5.0) == [None, None]


# ───────── الجمل ─────────
def test_sentences_split_on_pauses_and_punctuation_and_merge_short_ones():
    ws = [W("ليش", 0.0, 0.4), W("عيونك", 0.5, 1.0), W("بتتعب؟", 1.1, 1.8),
          W("جرّبي", 3.0, 3.5), W("القطرة", 3.6, 4.2), W("اللطيفة", 4.3, 5.0),
          W("هلأ", 7.0, 7.4)]
    s = ar.sentences(ws)
    assert [x["text"] for x in s] == ["ليش عيونك بتتعب؟", "جرّبي القطرة اللطيفة هلأ"]      # «هلأ» (0.4ث) قصيرة: انضمت للي قبلها
    assert s[0]["start"] == 0.0 and s[0]["end"] == 1.8 and s[1]["start"] == 3.0 and s[1]["end"] == 7.4
    short = ar.sentences([W("أول", 0.0, 0.3), W("ثاني", 1.0, 1.3), W("طويلة", 3.0, 3.6), W("جداً", 3.7, 5.5)], pause=0.6, min_len=1.0)
    assert len(short) == 2 and short[0]["text"] == "أول ثاني" and short[1]["start"] == 3.0                 # القصير انضم للي بعده
    assert ar.sentences([]) == [] and ar.sentences([W(" ", 0, 1)]) == []


def test_long_sentences_are_cut_at_their_biggest_pause():
    ws = [W(f"w{i}", i * 1.0, i * 1.0 + 0.9) for i in range(12)]            # 12 ثانية بلا وقفة ≥0.6
    ws[6] = W("w6", 6.5, 7.4)                                               # وقفة 0.6ث قبل الكلمة 6 (أكبر وقفة)
    s = ar.sentences(ws, pause=0.9, max_len=8.0)
    assert len(s) >= 2 and all(x["end"] - x["start"] <= 8.0 + 1e-9 for x in s)
    assert s[0]["end"] <= 6.0 + 1e-9 and s[1]["start"] >= 6.5 - 1e-9 or len(s) > 2
    assert sum(len(x["words"]) for x in s) == 12 and [w for x in s for w in x["words"]] == ws


def test_assign_by_time_follows_scene_durations_and_balanced_groups_are_even():
    sents = [{"start": i * 2.0, "end": i * 2.0 + 1.8, "text": f"s{i}"} for i in range(6)]            # 12 ثانية
    g = ar.assign_by_time(sents, [6.0, 3.0, 3.0], total=12.0)                                      # المشهد الأول نص الوقت
    assert g == [[0, 1, 2], [3, 4], [5]]
    assert sum(len(x) for x in g) == 6 and [i for x in g for i in x] == list(range(6))
    assert ar.assign_by_time([], [1.0, 2.0]) == [[], []] and ar.assign_by_time(sents, []) == []
    b = ar.balanced(sents, 3)
    assert b == [[0, 1], [2, 3], [4, 5]]
    assert ar.balanced(sents[:2], 4) == [[0], [1], [], []] and ar.balanced([], 3) == [[], [], []] and ar.balanced(sents, 0) == []
    many = [{"start": i, "end": i + 0.9, "text": "x"} for i in range(20)]
    groups = ar.balanced(many, 7)
    assert len(groups) == 7 and all(groups) and [i for g in groups for i in g] == list(range(20))
