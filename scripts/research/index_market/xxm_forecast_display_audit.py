"""Selected-period r4 forecast HTTP audit; same bounded P4 worker, no files."""
from .xxm_page_request_audit import parse_args, run


def main(argv=None):
    run(parse_args(argv), 'forecast')


if __name__ == '__main__':
    main()
