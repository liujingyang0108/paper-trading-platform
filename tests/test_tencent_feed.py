import unittest

from paper_trading_platform.feeds.tencent import parse_quote_line, vendor_symbol


class TencentFeedTest(unittest.TestCase):
    def test_vendor_symbol(self):
        self.assertEqual(vendor_symbol("510300.SH"), "sh510300")
        self.assertEqual(vendor_symbol("159915.SZ"), "sz159915")

    def test_parse_quote(self):
        parts = [""] * 90
        parts[2], parts[3], parts[4], parts[6] = "510300", "4.786", "4.726", "100"
        parts[9], parts[10], parts[19], parts[20] = "4.785", "20", "4.787", "30"
        parts[30], parts[47], parts[48] = "20260817143325", "5.199", "4.253"
        quote = parse_quote_line('v_sh510300="' + "~".join(parts) + '";')
        self.assertEqual(quote["symbol"], "510300.SH")
        self.assertEqual(quote["source"], "public_web")
        self.assertEqual(quote["bid_size"], 2000)


if __name__ == "__main__": unittest.main()
