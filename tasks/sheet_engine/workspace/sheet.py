"""Spreadsheet engine. See SPEC.md."""


class Sheet:
    def set(self, name, raw):
        raise NotImplementedError

    def get(self, name):
        raise NotImplementedError
