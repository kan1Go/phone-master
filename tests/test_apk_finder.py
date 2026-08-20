from unittest.mock import Mock, patch

from phone_master.adb.apk_finder import TENCENT_MYAPP_DIRS, find_candidate_paths, inspect_apk


def test_find_candidate_paths_includes_myapp_and_batches_search():
    client = Mock()
    client.find_files_many.return_value = ["/one.apk", "/one.apk", "/two.apk"]

    assert find_candidate_paths(client, ["example.app"]) == ["/one.apk", "/two.apk"]
    directories, pattern = client.find_files_many.call_args.args
    assert pattern == "*.apk"
    assert all(directory in directories for directory in TENCENT_MYAPP_DIRS)
    assert "/sdcard/Android/data/example.app" in directories


def test_inspect_apk_reuses_metadata_when_device_file_is_unchanged(tmp_path):
    client = Mock()
    client.file_signature.return_value = "123:456"
    client.pull_file.return_value = True

    with patch("phone_master.adb.apk_finder.APK") as apk_type:
        apk_type.return_value.get_package.return_value = "example.app"
        apk_type.return_value.get_androidversion_name.return_value = "2.0"
        first = inspect_apk(client, "/device/update.apk", str(tmp_path))
        second = inspect_apk(client, "/device/update.apk", str(tmp_path))

    assert first == second
    client.pull_file.assert_called_once()
