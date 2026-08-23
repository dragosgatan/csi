import unittest

from capture import parse_packet


class CapturePacketTests(unittest.TestCase):
    def test_parses_node_id_header(self):
        raw_values = bytearray(range(118))
        raw_values[-1] = 255
        packet = b"7,12345,-48,118," + raw_values

        parsed = parse_packet(packet)

        self.assertIsNotNone(parsed)
        node_id, rssi, parsed_raw_values = parsed
        self.assertEqual(node_id, 7)
        self.assertEqual(rssi, -48)
        self.assertEqual(parsed_raw_values[0], 0)
        self.assertEqual(parsed_raw_values[-1], -1)
        self.assertEqual(len(parsed_raw_values), 118)

    def test_rejects_old_header_without_node_id(self):
        raw_values = bytes(range(118))

        self.assertIsNone(parse_packet(b"12345,-48,118," + raw_values))


if __name__ == "__main__":
    unittest.main()
