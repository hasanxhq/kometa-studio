import stat

from kometa_studio.crypto import KEY_FILE, SecretBox


def test_round_trip_with_a_persistent_key(tmp_path):
    ciphertext = SecretBox.load_or_create(tmp_path).encrypt("acct-token")
    assert "acct-token" not in ciphertext
    assert SecretBox.load_or_create(tmp_path).decrypt(ciphertext) == "acct-token"


def test_key_file_is_private(tmp_path):
    SecretBox.load_or_create(tmp_path)
    assert stat.S_IMODE((tmp_path / KEY_FILE).stat().st_mode) == 0o600


def test_a_lost_key_means_signing_in_again(tmp_path):
    ciphertext = SecretBox.load_or_create(tmp_path / "old").encrypt("acct-token")
    assert SecretBox.load_or_create(tmp_path / "new").decrypt(ciphertext) is None
