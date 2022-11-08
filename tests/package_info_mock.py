from typing import List, Optional, NamedTuple


# A stand-in for pip._internal.commands.show._PackageInfo, as returned by
# search_packages_info from the same module
class _PackageInfo(NamedTuple):
    name: str
    location: str
    files: Optional[List[str]]
