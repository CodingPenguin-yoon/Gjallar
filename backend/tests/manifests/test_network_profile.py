"""RED tests for NetworkProfile node bridge resolution."""

import unittest


class NetworkProfileTests(unittest.TestCase):
    def _load_networks(self):
        try:
            from app.manifests.loader import load_builtin_network_profiles
        except ModuleNotFoundError as exc:
            self.fail(
                "Expected app.manifests.loader.load_builtin_network_profiles for PRD "
                f"network profile loading, but it is missing: {exc}"
            )
        return {network.network_id: network for network in load_builtin_network_profiles()}

    def test_server_net_maps_both_mvp_nodes_to_vmbr0(self):
        networks = self._load_networks()
        server_net = networks.get("server-net")
        self.assertIsNotNone(server_net, "server-net NetworkProfile must exist")
        self.assertEqual("vmbr0", server_net.resolve_bridge("yoonmanserver2"))
        self.assertEqual("vmbr0", server_net.resolve_bridge("yoonmanserver3"))

    def test_unknown_node_bridge_mapping_is_red_risk(self):
        networks = self._load_networks()
        server_net = networks.get("server-net")
        with self.assertRaisesRegex(ValueError, "red risk"):
            server_net.resolve_bridge("unknown-node")


if __name__ == "__main__":
    unittest.main()
