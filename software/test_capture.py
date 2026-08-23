import unittest

from capture import CsiCollector, parse_packet


class CapturePacketTests(unittest.TestCase):
    def test_parses_mesh_link_header(self):
        raw_values = bytearray(range(118))
        raw_values[-1] = 255
        packet = b"AABBCCDDEEFF,112233445566,12345,-48,118," + raw_values

        parsed = parse_packet(packet)

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.rx_mac, "AABBCCDDEEFF")
        self.assertEqual(parsed.tx_mac, "112233445566")
        self.assertEqual(parsed.rssi, -48)
        self.assertEqual(parsed.raw_values[0], 0)
        self.assertEqual(parsed.raw_values[-1], -1)
        self.assertEqual(len(parsed.raw_values), 118)

    def test_rejects_old_node_id_header(self):
        raw_values = bytes(range(118))

        self.assertIsNone(parse_packet(b"12345,-48,118," + raw_values))

    def test_calibrate_clears_node_filter_state(self):
        collector = CsiCollector(filter_window_size=3)
        raw_values = bytes(
            value for pair in ([20, 0] for _ in range(59)) for value in pair
        )
        packet = f"AABBCCDDEEFF,112233445566,12345,-42,{len(raw_values)},".encode() + raw_values

        collector._handle_packet(packet, "127.0.0.1")
        collector.calibrate()
        snapshot = collector.get_snapshot()

        self.assertEqual(snapshot["packet_count"], 1)
        self.assertEqual(snapshot["links"][0]["rx_mac"], "AABBCCDDEEFF")
        self.assertEqual(snapshot["links"][0]["history"], [])
        self.assertEqual(snapshot["links"][0]["motion_score"], 0.0)
        self.assertIsNotNone(snapshot["calibrated_at"])


if __name__ == "__main__":
    unittest.main()
