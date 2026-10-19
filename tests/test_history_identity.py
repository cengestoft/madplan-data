"""Identity check for history matching: equal normalized_product_key is NOT enough.

Names below are generic product descriptions that mirror the concrete false matches found in the 13 Oct 2026 revision.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from history_identity import REJECTED, REVIEW, VERIFIED, combine, compare, describe, key_status, raw_id_hash, history_integrity


def verdict(raw, offer):
    return compare(describe(raw), describe(offer))


def rec(name, brand, amount, unit, count=1):
    return {"name": name, "brand": brand, "package_amount": amount, "package_unit": unit, "package_count": count}


class ConcreteFalseMatches(unittest.TestCase):
    def test_minced_beef_is_not_chicken(self):
        v = verdict(rec("Hakket kylling 3-7%, 400 g", "Netto", 400, "g"), rec("Netto Hakket oksekød 8-12%", "Netto", 400, "g"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("meat", v["conflicts"])

    def test_minced_beef_is_not_pork(self):
        v = verdict(rec("Hakket grisekød 8-12% fedt øko 400 g", "ØGO", 400, "g"), rec("ØGO Hakket oksekød 8-12% øko", "ØGO", 400, "g"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("meat", v["conflicts"])

    def test_veal_and_pork_is_not_pure_pork(self):
        v = verdict(rec("Hakket grisekød 14-18% fedt 1 kg", "Velsmag", 1, "kg"), rec("Velsmag Hakket kalv- og grisekød 8-12%", "Velsmag", 1, "kg"))
        self.assertEqual(v["status"], REJECTED)

    def test_sour_cream_onion_is_not_sea_salt(self):
        v = verdict(rec("Chips m. havsalt 95 g", "KiMs", 95, "g"), rec("KiMs Chips Sour Cream & Onion", "KiMs", 95, "g"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("flavour", v["conflicts"])

    def test_vanilla_skyr_is_not_strawberry_yoghurt(self):
        v = verdict(rec("Yoghurt m. jordbær, chia og vanilje 0,2% fedt 1 kg", "Cheasy", 1, "kg"), rec("Cheasy Skyr Vanilje 0,2%", "Cheasy", 1, "kg"))
        self.assertNotEqual(v["status"], VERIFIED)

    def test_other_capri_sun_flavour(self):
        v = verdict(rec("Capri-Sun Fairy Drink multifrugt 10 x 200 ml", "Capri-Sun", 200, "ml", 10), rec("Capri-Sun Jungle Drink", "Capri-Sun", 200, "ml", 10))
        self.assertNotEqual(v["status"], VERIFIED)

    def test_cottage_cheese_fat_percentage(self):
        v = verdict(rec("Hytteost 4% fedt 200 g", "Mammen", 200, "g"), rec("Mammen Hytteost 1,5%", "Mammen", 200, "g"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("fat_percent", v["conflicts"])

    def test_cottage_cheese_missing_fat_percentage_needs_review(self):
        v = verdict(rec("Hytteost 4% fedt 450 g", "Gestus", 450, "g"), rec("Gestus Hytteost", "Gestus", 450, "g"))
        self.assertEqual(v["status"], REVIEW); self.assertIn("fat_percent", v["missing"])

    def test_smoked_vs_cured_salmon(self):
        v = verdict(rec("Gravad laks i skiver 100 g", "Premieur", 100, "g"), rec("Premieur Laks i skiver", "Premieur", 100, "g"))
        self.assertNotEqual(v["status"], VERIFIED)


class SpecialCases(unittest.TestCase):
    def test_same_product_with_different_names_verifies(self):
        v = verdict(rec("Stryhn's Grovhakket leverpostej 400 g", "Stryhn's", 400, "g"), rec("Stryhn's Leverpostej grovhakket", "Stryhn's", 400, "g"))
        self.assertEqual(v["status"], VERIFIED)

    def test_different_products_with_same_pack_size_never_verify(self):
        v = verdict(rec("Salling Princip surdejsbrød 750 g", "Salling Princip", 750, "g"), rec("Salling Princip Clementiner", "Salling Princip", 750, "g"))
        self.assertEqual(v["status"], REJECTED)

    def test_unknown_brand_is_not_approved(self):
        v = verdict(rec("Mælk 1 l", "", 1, "l"), rec("Arla Mælk", "Arla", 1, "l"))
        self.assertEqual(v["status"], REVIEW); self.assertIn("brand", v["missing"])

    def test_other_brand_is_rejected(self):
        v = verdict(rec("Mørk chokoladeplade Ferrero Rocher 90 g", "Ferrero Rocher", 90, "g"), rec("Daim Chokoladeplade", "Daim", 90, "g"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("brand", v["conflicts"])

    def test_missing_variant_information_is_not_approved(self):
        v = verdict(rec("Chips 150 g", "KiMs", 150, "g"), rec("KiMs Chips Sour Cream & Onion", "KiMs", 150, "g"))
        self.assertNotEqual(v["status"], VERIFIED)

    def test_multipack_versus_single(self):
        v = verdict(rec("Coca-Cola Original 33 cl", "Coca-Cola", 33, "cl", 1), rec("Coca-Cola Original 6 x 33 cl", "Coca-Cola", 33, "cl", 6))
        self.assertEqual(v["status"], REJECTED); self.assertIn("pack_count", v["conflicts"])

    def test_coca_cola_original_zero_light_are_three_products(self):
        cola = lambda name: rec(name, "Coca-Cola", 33, "cl", 24)
        names = {"original": "Coca-Cola Original 24 x 33 cl", "zero": "Coca-Cola Zero 24 x 33 cl", "light": "Coca-Cola Light 24 x 33 cl"}
        for a in names:
            for b in names:
                v = verdict(cola(names[a]), cola(names[b]))
                self.assertEqual(v["status"] == VERIFIED, a == b, (a, b, v))

    def test_same_package_in_g_and_kg_is_the_same_size(self):
        v = verdict(rec("Rugbrød 500 g", "Schulstad", 500, "g"), rec("Schulstad Rugbrød 0,5 kg", "Schulstad", 0.5, "kg"))
        self.assertEqual(v["status"], VERIFIED)

    def test_different_unit_family_conflicts(self):
        v = verdict(rec("Olie 1 kg", "Basso", 1, "kg"), rec("Basso Olie 1 l", "Basso", 1, "l"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("unit", v["conflicts"])

    def test_organic_is_a_different_product(self):
        v = verdict(rec("Mou Økologisk tomatsuppe 1 kg", "Mou", 1, "kg"), rec("Mou Tomatsuppe", "Mou", 1, "kg"))
        self.assertEqual(v["status"], REJECTED); self.assertIn("variant", v["conflicts"])

    def test_light_butter_is_not_regular_butter(self):
        v = verdict(rec("Lurpak Let saltet smør 200 g", "Lurpak", 200, "g"), rec("Lurpak Smør saltet 200 g", "Lurpak", 200, "g"))
        self.assertEqual(v["status"], REJECTED)

    def test_raw_feed_without_brand_field_uses_brand_in_the_name(self):
        v = verdict(rec("Steff Houlberg, Bayerske pølser, Bayerske pølser 67% kød", None, 375, "g"), rec("Steff Houlberg Bayerske Pølser", "Steff Houlberg", 375, "g"))
        self.assertEqual(v["status"], VERIFIED)


class Combining(unittest.TestCase):
    def test_ambiguous_offers_under_one_key_need_review(self):
        raw = rec("Barebells Soft Protein Bar Banana Dream", "Barebells", 55, "g")
        a = verdict(raw, rec("Barebells Banana Dream Proteinbar", "Barebells", 55, "g"))
        b = verdict(raw, rec("Barebells Salty Peanut Proteinbar", "Barebells", 55, "g"))
        c = combine([a, b])
        self.assertEqual(c["status"], REVIEW)
        self.assertIn("ambiguous_offers", c["missing"])

    def test_all_review_verdicts_collect_missing_reasons(self):
        first = {"status": REVIEW, "fields": {"product_type": "missing"}, "conflicts": [], "missing": ["product_type"]}
        second = {"status": REVIEW, "fields": {"flavour": "missing"}, "conflicts": [], "missing": ["flavour"]}
        for verdicts in ([first, second], [second, first]):
            combined = combine(verdicts)
            self.assertEqual(combined["status"], REVIEW)
            self.assertEqual(combined["missing"], ["flavour", "product_type"])
            self.assertEqual(combined["conflicts"], [])

    def test_key_status_rules(self):
        self.assertEqual(key_status({VERIFIED: 1, REVIEW: 3}), VERIFIED)
        self.assertEqual(key_status({REVIEW: 1, REJECTED: 2}), REVIEW)
        self.assertEqual(key_status({REJECTED: 2}), REJECTED)
        self.assertEqual(key_status({}), "no_candidate")


class ImporterEndToEnd(unittest.TestCase):
    """Runs the real importer on a tiny synthetic raw file: only verified rows reach the public history."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        offers = [dict(id=f"o{i}", store="Netto", category="chips", price_dkk=20, package_amount=a, package_unit=u, name=n, brand=b,
                       valid_from="2026-10-05", valid_to="2026-10-12") for i, (n, b, a, u) in enumerate([
            ("KiMs Sour Cream & Onion Chips", "KiMs", 150, "g"), ("KiMs Havsalt Chips", "KiMs", 150, "g"),
            ("Gestus Hytteost", "Gestus", 450, "g")])]
        from product_normalization import normalized_product_key
        for o in offers: o["normalized_product_key"] = normalized_product_key(o)
        (self.tmp / "current.json").write_text(json.dumps({"generated_at": "2026-10-09T08:00:00+02:00", "offers": offers}), encoding="utf-8")
        hist = lambda price, q, u: [{"date": f"2026-0{m}-15", "price": price, "quantity": q, "unit": u} for m in (6, 7, 8)]
        raw = [{"store": "netto", "id": "1", "name": "KiMs, Chips med Sour Cream & Onion., Chips m. sour cream & onion", "category": "0", "priceHistory": hist(20, 150, "g")},
               {"store": "netto", "id": "2", "name": "KiMs, Havsalt Chips., Chips m. havsalt", "category": "0", "priceHistory": hist(21, 150, "g")},
               {"store": "netto", "id": "3", "name": "Gestus, Hytteost 4% fedt 450g, Hytteost", "category": "0", "priceHistory": hist(15, 450, "g")}]
        (self.tmp / "raw.json").write_text(json.dumps(raw), encoding="utf-8")

    def run_import(self, *extra):
        out = subprocess.run([sys.executable, str(ROOT / "scripts" / "import_dagligepriser_history.py"), "--source-file", str(self.tmp / "raw.json"),
                              "--current-offers", str(self.tmp / "current.json"), "--output", str(self.tmp / "monthly.json"),
                              "--decisions", str(self.tmp / "decisions.json"),
                              "--identities", str(self.tmp / "identities.json"),
                              *(() if "--previous-verification" in extra else ("--previous-verification", str(self.tmp / "no-previous.json"))), *extra], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads((self.tmp / "monthly.json").read_text(encoding="utf-8")), json.loads((self.tmp / "history_verification.json").read_text(encoding="utf-8"))

    def test_unverified_quantity_offer_is_held_and_others_unaffected(self):
        cur = json.loads((self.tmp / "current.json").read_text(encoding="utf-8"))
        havsalt = next(o for o in cur["offers"] if "Havsalt" in o["name"])
        havsalt["quantity_status"] = "unverified"
        (self.tmp / "current.json").write_text(json.dumps(cur), encoding="utf-8")
        monthly, ver = self.run_import()
        self.assertEqual(ver["keys"][havsalt["normalized_product_key"]]["status"], REVIEW)
        self.assertEqual(ver["keys"][havsalt["normalized_product_key"]]["held"], ["quantity_unverified"])
        self.assertEqual(ver["keys"][havsalt["normalized_product_key"]]["raw_products"]["verified"], 1)  # raw matches stay visible
        self.assertEqual({r["normalized_product_key"] for r in monthly["records"]} & {havsalt["normalized_product_key"]}, set())
        sour = next(o for o in cur["offers"] if "Sour" in o["name"])
        self.assertEqual(ver["keys"][sour["normalized_product_key"]]["status"], VERIFIED)  # other products unaffected
        self.assertNotIn("held", ver["keys"][sour["normalized_product_key"]])

    def test_only_verified_history_is_published(self):
        monthly, ver = self.run_import()
        statuses = {k.split("|")[1][8:]: v["status"] for k, v in ver["keys"].items()}
        self.assertEqual(statuses["sour-cream-onion-chips"], VERIFIED)
        self.assertEqual(statuses["havsalt-chips"], VERIFIED)
        self.assertEqual(statuses["hytteost"], REVIEW)  # fat percentage missing on the offer side
        self.assertIs(monthly["verified_only"], True)
        self.assertEqual({r["normalized_product_key"].split("|")[1][8:] for r in monthly["records"]}, {"sour-cream-onion-chips", "havsalt-chips"})
        self.assertEqual(ver["summary"]["verified"], 2); self.assertEqual(ver["summary"]["review_required"], 1)
        self.assertEqual(ver["summary"]["additional_verified_needed"], 0)  # 2 of 3 active keys verified in this tiny fixture
        for raw_text in ("Chips m. havsalt", "Chips med Sour Cream", "Hytteost 4% fedt"):  # raw product text must not reach the public file
            self.assertNotIn(raw_text, json.dumps(ver))

    def write_offers(self, names):
        """Replace current offers by the given subset of the fixture offers (keys stay the same)."""
        cur = json.loads((self.tmp / "current.json").read_text(encoding="utf-8"))
        full = cur.get("_all") or cur["offers"]
        cur["_all"] = full
        cur["offers"] = [o for o in full if o["name"] in names]
        (self.tmp / "current.json").write_text(json.dumps(cur), encoding="utf-8")

    def havsalt_rows(self, monthly):
        return [r for r in monthly["records"] if r["normalized_product_key"].split("|")[1] == "product=havsalt-chips"]

    def test_history_is_kept_when_a_product_loses_its_offer_and_reused_when_it_returns(self):
        monthly1, ver1 = self.run_import()
        before = self.havsalt_rows(monthly1)
        self.assertTrue(before)
        # the havsalt offer expires: only the other two offers are active now
        self.write_offers({"KiMs Sour Cream & Onion Chips", "Gestus Hytteost"})
        monthly2, ver2 = self.run_import()
        key = next(k for k in ver2["keys"] if k.split("|")[1] == "product=havsalt-chips")
        self.assertEqual(self.havsalt_rows(monthly2), before, "verified history must survive a missing offer")
        self.assertEqual(ver2["keys"][key]["status"], VERIFIED)
        self.assertIs(ver2["keys"][key]["active"], False)
        # overlap and graph options are measured on ACTIVE keys only
        self.assertEqual(ver2["summary"]["active_food_keys"], 2)
        self.assertEqual(ver2["summary"]["verified"], 1)
        self.assertEqual(ver2["summary"]["retained_verified_keys_without_active_offer"], 1)
        # the offer returns: same history is reused, key active again
        self.write_offers({"KiMs Sour Cream & Onion Chips", "KiMs Havsalt Chips", "Gestus Hytteost"})
        monthly3, ver3 = self.run_import()
        self.assertEqual(self.havsalt_rows(monthly3), before)
        self.assertIs(ver3["keys"][key]["active"], True)
        self.assertEqual(ver3["summary"]["verified"], 2)

    def test_verified_history_survives_when_ALL_current_offers_expire(self):
        monthly1, ver1 = self.run_import()
        self.write_offers(set())  # every offer expired: current_offers is empty
        monthly2, ver2 = self.run_import()
        self.assertEqual(monthly2["records"], monthly1["records"], "verified history must not shrink")
        self.assertEqual(ver2["summary"]["active_food_keys"], 0)
        self.assertEqual(ver2["summary"]["retained_verified_keys_without_active_offer"], ver1["summary"]["verified"])
        self.assertTrue(all(v["active"] is False for v in ver2["keys"].values()))
        self.assertEqual(history_integrity(monthly2, ver2)["rows_unverified"], 0)

    def test_unverified_history_is_never_published_even_for_keys_without_active_offer(self):
        self.run_import()
        self.write_offers({"KiMs Sour Cream & Onion Chips", "KiMs Havsalt Chips"})  # hytteost offer gone, but still in the registry
        monthly, ver = self.run_import()
        hyt = next(k for k in ver["keys"] if k.split("|")[1] == "product=hytteost")
        self.assertEqual(ver["keys"][hyt]["status"], REVIEW)
        self.assertIs(ver["keys"][hyt]["active"], False)
        self.assertNotIn(hyt, {r["normalized_product_key"] for r in monthly["records"]})
        self.assertEqual(history_integrity(monthly, ver)["rows_unverified"], 0)

    def test_human_approval_without_documenting_evidence_is_not_applied(self):
        raw = json.loads((self.tmp / "raw.json").read_text(encoding="utf-8"))
        hist = [{"date": f"2026-0{m}-15", "price": 17, "quantity": 450, "unit": "g"} for m in (6, 7, 8)]
        raw.append({"store": "netto", "id": "7", "name": "Gestus, Hytteost Naturel 4% fedt 450g, Hytteost", "category": "0", "priceHistory": hist})
        (self.tmp / "raw.json").write_text(json.dumps(raw), encoding="utf-8")
        _, ver = self.run_import()
        key = next(k for k in ver["keys"] if k.split("|")[1] == "product=hytteost")
        (self.tmp / "decisions.json").write_text(json.dumps({"decisions": [
            {"normalized_product_key": key, "raw_id_hash": raw_id_hash("netto", "7"), "decision": "verified", "reviewed_by": "Casper",
             "reviewed_on": "2026-10-13"}]}), encoding="utf-8")
        monthly, ver2 = self.run_import()
        self.assertEqual(ver2["keys"][key]["status"], REVIEW, "extra distinctive word 'naturel' is not documented by the offer")
        self.assertEqual(ver2["keys"][key]["manual_decisions_blocked"], 1)
        self.assertEqual(ver2["keys"][key]["manual_decisions"], 0)
        self.assertNotIn(key, {r["normalized_product_key"] for r in monthly["records"]})

    def test_identity_registry_holds_no_raw_text(self):
        self.run_import()
        text = (self.tmp / "identities.json").read_text(encoding="utf-8")
        for raw_text in ("Chips m. havsalt", "Chips med Sour Cream", "Hytteost 4% fedt"):
            self.assertNotIn(raw_text, text)
        self.assertIs(json.loads(text)["raw_data_included"], False)

    def test_mixed_candidates_never_leak_unverified_prices(self):
        """One key with a verified raw product AND rejected/review raw products: only the verified prices reach the aggregate."""
        raw = json.loads((self.tmp / "raw.json").read_text(encoding="utf-8"))
        hist = lambda price: [{"date": f"2026-0{m}-15", "price": price, "quantity": 150, "unit": "g"} for m in (6, 7, 8)]
        raw += [{"store": "netto", "id": "4", "name": "KiMs, Havsalt Chips Light., Chips m. havsalt light", "category": "0", "priceHistory": hist(99)},
                {"store": "netto", "id": "5", "name": "Pringles, Havsalt Chips., Chips m. havsalt", "category": "0", "priceHistory": hist(77)},
                {"store": "netto", "id": "6", "name": "KiMs, Havsalt Chips., Chips m. havsalt", "category": "0", "priceHistory": hist(21)}]
        (self.tmp / "raw.json").write_text(json.dumps(raw), encoding="utf-8")
        monthly, ver = self.run_import()
        key = next(k for k in ver["keys"] if k.split("|")[1] == "product=havsalt-chips")
        self.assertEqual(ver["keys"][key]["status"], VERIFIED)
        prices = {r["median_price_dkk"] for r in monthly["records"] if r["normalized_product_key"] == key}
        self.assertEqual(prices, {21}, "unverified candidates (Light 99, Pringles 77) must not enter the aggregate")
        self.assertTrue(all(r["observation_count"] <= 2 for r in monthly["records"] if r["normalized_product_key"] == key))

    def test_human_decision_can_promote_review_but_not_override_conflict(self):
        _, ver = self.run_import()
        key = next(k for k in ver["keys"] if k.split("|")[1] == "product=hytteost")
        decisions = {"decisions": [
            {"normalized_product_key": key, "raw_id_hash": raw_id_hash("netto", "3"), "decision": "verified", "reviewed_by": "Casper", "reviewed_on": "2026-10-13"}]}
        (self.tmp / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
        monthly, ver2 = self.run_import()
        self.assertEqual(ver2["keys"][key]["status"], VERIFIED)
        self.assertEqual(ver2["keys"][key]["manual_decisions"], 1)
        # a decision without reviewer/date is ignored; and a hard conflict can never be promoted
        sour = next(k for k in ver["keys"] if k.split("|")[1] == "product=sour-cream-onion-chips")
        decisions["decisions"] = [{"normalized_product_key": sour, "raw_id_hash": raw_id_hash("netto", "2"), "decision": "verified"}]
        (self.tmp / "decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
        _, ver3 = self.run_import()
        self.assertEqual(ver3["keys"][sour]["raw_products"][VERIFIED], 1)


class HistoryIntegrity(unittest.TestCase):
    VER = {"keys": {
        "a": {"status": "verified", "months": 3, "raw_products": {"verified": 1}},
        "b": {"status": "review_required", "months": 0, "raw_products": {"review_required": 1}},
        "c": {"status": "verified", "months": 0, "raw_products": {"verified": 1}},
        "d": {"status": "verified", "months": 2, "raw_products": {"verified": 0}},
    }}

    def hist(self, *keys):
        return {"verified_only": True, "records": [{"normalized_product_key": k} for k in keys]}

    def test_clean_history_has_no_findings(self):
        ver = {"keys": {"a": self.VER["keys"]["a"]}}
        r = history_integrity(self.hist("a", "a"), ver)
        self.assertEqual((r["rows_total"], r["rows_unverified"], r["verified_without_history"], r["verified_without_raw"]), (2, 0, [], []))

    def test_row_with_review_required_key_is_flagged(self):
        self.assertEqual(history_integrity(self.hist("a", "b"), self.VER)["rows_unverified"], 1)

    def test_row_with_unknown_key_is_flagged(self):
        self.assertEqual(history_integrity(self.hist("zzz"), self.VER)["rows_unverified"], 1)

    def test_verified_without_history_or_raw_product_is_flagged(self):
        r = history_integrity(self.hist("a", "d"), self.VER)
        self.assertEqual(r["verified_without_history"], ["c"])  # no rows, months 0
        self.assertEqual(r["verified_without_raw"], ["d"])

    def test_missing_verification_file_is_reported(self):
        r = history_integrity(self.hist("a"), None)
        self.assertFalse(r["verification_file_present"]); self.assertEqual(r["rows_unverified"], 1)


if __name__ == "__main__":
    unittest.main()
