"""The conservative history matcher must never join different products or brands."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_dagligepriser_history import conservative_score, slug, toks


def score(raw_brand, raw_name, cand_brand, cand_name):
    return conservative_score(slug(raw_brand), toks(raw_name), slug(cand_brand), toks(cand_name))


class ConservativeMatch(unittest.TestCase):
    def test_different_brands_never_match(self):
        self.assertIsNone(score("Ferrero Rocher", "Mørk chokoladeplade 90 g", "Daim", "Daim chokoladeplade 90 g"))
        self.assertIsNone(score("Kinder Bueno", "Chokoladebar 43 g", "Snickers", "Snickers chokoladebar 43 g"))
        self.assertIsNone(score("Arla Protein", "Protein pudding karamel", "Milbona", "Milbona High Protein Pudding Caramel"))
        self.assertIsNone(score("Absolut", "Vodka Citron 70 cl", "Smirnoff", "Smirnoff Vodka 70 cl"))

    def test_empty_brand_on_either_side_never_matches(self):
        self.assertIsNone(score("", "Cola Light 33 cl", "Dr Pepper", "Dr Pepper Cola 33 cl"))
        self.assertIsNone(score("Harboe", "Harboe Cola", "", "Cola"))

    def test_same_brand_but_different_product_never_matches(self):
        # Salling Princip bread must not become Salling Princip clementines because the brand words overlap.
        self.assertIsNone(score("Salling Princip", "Salling princip rug levain 750g Surdejsbrød", "Salling Princip", "Salling Princip Clementiner"))
        self.assertIsNone(score("Graasten", "Graasten sennep 375 g", "Graasten", "Graasten Remoulade"))

    def test_same_brand_and_product_with_naming_difference_matches(self):
        self.assertIsNotNone(score("Stryhn's", "Grovhakket leverpostej", "Stryhn's", "Stryhn's Grovhakket Leverpostej 400 g"))
        self.assertGreaterEqual(score("Barebells", "Soft Protein Bar Banana Dream", "Barebells", "Barebells Banana Dream proteinbar"), 0.5)


if __name__ == "__main__":
    unittest.main()
