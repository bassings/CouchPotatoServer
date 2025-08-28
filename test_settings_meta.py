from couchpotato.core.settings import Settings


def test_option_meta_readonly_and_hidden(tmp_path):
    cfg = tmp_path / 'settings.conf'
    s = Settings()
    s.setFile(str(cfg))
    sec = 'core'
    s.addSection(sec)

    # Prepare a normal option
    s.setType(sec, 'normal', 'unicode')
    s.p.set(sec, 'normal', 'value')

    # Mark another option as readonly via meta
    meta = s.optionMetaSuffix()
    s.p.set(sec, 'ro_opt' + meta, 'ro')
    s.p.set(sec, 'ro_opt', '42')

    # Mark a third option as hidden
    s.p.set(sec, 'hidden_opt' + meta, 'hidden')
    s.p.set(sec, 'hidden_opt', 'secret')

    # Section visibility default: readable
    assert s.isSectionReadable(sec) is True

    # Readability
    assert s.isOptionReadable(sec, 'normal') is True
    assert s.isOptionReadable(sec, 'ro_opt') is True
    assert s.isOptionReadable(sec, 'hidden_opt') is False

    # Writability
    assert s.isOptionWritable(sec, 'normal') is True
    assert s.isOptionWritable(sec, 'ro_opt') is False
    # Hidden implies not writable
    assert s.isOptionWritable(sec, 'hidden_opt') is False

