from aula.models import SfoWebStatus


def test_sfoweb_status_is_serializable():
    status = SfoWebStatus(
        status="Kommet",
        time="07:40",
        raw_text="Kommet kl. 07:40",
    )

    assert dict(status) == {
        "status": "Kommet",
        "time": "07:40",
        "raw_text": "Kommet kl. 07:40",
    }
