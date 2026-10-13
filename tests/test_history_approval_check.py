"""Approvals are only DOCUMENTED when offer and raw product name the same product line (distinctive words equal)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from history_approval_check import documented, raw_title


def ok(offer, brand, raw):
    return documented([offer], brand, raw)[0]


class DocumentedApprovals(unittest.TestCase):
    def test_same_product_with_extra_descriptive_text_on_raw_side(self):
        self.assertTrue(ok("Barebells Creamy Crisp Proteinbar", "Barebells", "Barebells, Creamy Crisp, Proteinbar m. karamelsauce og mælkechokolade"))
        self.assertTrue(ok("Cheasy Skovbær Skyr", "Cheasy", "Cheasy, Skyr med skovbær 0,2%, Skyr m. skovbær 0,2% fedt u. tilsat sukker"))
        self.assertTrue(ok("Coca Cola Zero Cola 24 pk.", "Coca-Cola Zero", "Coca Cola Zero 24X25cl Pet, 600 CL"))

    def test_decimal_comma_does_not_split_the_title(self):
        self.assertEqual(raw_title("Cheasy Skyr Skovbær 0,2%, 1000 GR"), "Cheasy Skyr Skovbær 0,2%")

    def test_different_flavour_or_variant_is_not_documented(self):
        self.assertFalse(ok("Barebells White Salty Peanut Proteinbar", "Barebells", "Barebells, Salty Peanut proteinbar, Proteinbar m. saltede peanuts"))
        self.assertFalse(ok("Ben & Jerry's Cookie Dough is", "Ben & Jerry's", "Ben & Jerry's, Cookie Dough S'Wich Up Dessert Is, Flødeis"))
        self.assertFalse(ok("Riberhus Skiveost Danbo Mellemlagret", "Riberhus", "Riberhus, Danbo Mellemlagret med kommen, Danbo ost i skiver"))

    def test_skyr_is_not_yoghurt(self):
        self.assertFalse(ok("Cheasy Vanilje Skyr", "Cheasy", "Cheasy, Yoghurt vanilje, Yoghurt m. vanilje 0,1% fedt"))

    def test_extra_distinctive_word_on_either_side_blocks(self):
        self.assertFalse(ok("Blue Dragon Satay Curry Sauce", "Blue Dragon", "Blue Dragon, Blue Dragon Indonesian Satay Curry 350g, Peanut sataysauce"))
        self.assertFalse(ok("Kims Ostepops Original", "Kims", "Kims Ostepops, 75 Gram"))

    def test_equal_key_or_brand_alone_is_never_enough(self):
        self.assertFalse(ok("Wasa Sesam & Havsalt knækbrød", "Wasa", "Wasa, Runda Sesam-Havsalt, Hvedeknækbrød m. sesam og havsalt"))
        self.assertFalse(ok("Vici Gyoza Dumplings with Pork", "Vici", "VICI, Gyoza dumplings with vegetables 200 g, Dumplings m. grøntsager"))

    def test_several_offers_under_one_key_must_all_agree(self):
        self.assertFalse(documented(["Barebells Creamy Crisp", "Barebells Salty Peanut"], "Barebells", "Barebells, Creamy Crisp, Proteinbar")[0])


if __name__ == "__main__":
    unittest.main()
