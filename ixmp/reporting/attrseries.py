from collections.abc import Collection

import pandas as pd
import pandas.core.indexes.base as ibase
import pint
import xarray as xr


class AttrSeries(pd.Series):
    """:class:`pandas.Series` subclass imitating :class:`xarray.DataArray`.

    Future versions of :mod:`ixmp.reporting` will use :class:`xarray.DataArray`
    as :class:`Quantity`; however, because :mod:`xarray` currently lacks sparse
    matrix support, ixmp quantities may be too large for available memory.

    The AttrSeries class provides similar methods and behaviour to
    :class:`xarray.DataArray`, so that :mod:`ixmp.reporting.computations`
    methods can use xarray-like syntax.

    Parameters
    ----------
    units : str or pint.Unit, optional
        Set the units attribute. The value is converted to :class:`pint.Unit`
        and added to `attrs`.
    attrs : :class:`~collections.abc.Mapping`, optional
        Set the :attr:`~pandas.Series.attrs` of the AttrSeries. This attribute
        was added in `pandas 1.0
        <https://pandas.pydata.org/docs/whatsnew/v1.0.0.html>`_, but is not
        currently supported by the Series constructor.
    """

    # See https://pandas.pydata.org/docs/development/extending.html
    @property
    def _constructor(self):
        return AttrSeries

    def __init__(self, data=None, *args, name=None, units=None, attrs=None,
                 **kwargs):
        attrs = attrs or dict()
        if units:
            # Insert the units into the attrs
            attrs['_unit'] = pint.Unit(units)

        if isinstance(data, (AttrSeries, xr.DataArray)):
            # Use attrs from an existing object
            new_attrs = data.attrs.copy()

            # Overwrite with explicit attrs argument
            new_attrs.update(attrs)
            attrs = new_attrs

            # Pre-convert to pd.Series from xr.DataArray to preserve names and
            # labels. For AttrSeries, this is a no-op (see below).
            name = ibase.maybe_extract_name(name, data, type(self))
            data = data.to_series()

        # Don't pass attrs to pd.Series constructor; it currently does not
        # accept them
        super().__init__(data, *args, name=name, **kwargs)

        # Update the attrs after initialization
        self.attrs.update(attrs)

    @classmethod
    def from_series(cls, series, sparse=None):
        return cls(series)

    def assign_attrs(self, d):
        self.attrs.update(d)
        return self

    def assign_coords(self, **kwargs):
        return pd.concat([self], keys=kwargs.values(), names=kwargs.keys())

    @property
    def coords(self):
        """Read-only."""
        result = dict()
        for name, levels in zip(self.index.names, self.index.levels):
            result[name] = xr.Dataset(None, coords={name: levels})[name]
        return result

    @property
    def dims(self):
        return tuple(self.index.names)

    def drop(self, label):
        return self.droplevel(label)

    def rename(self, new_name_or_name_dict):
        if isinstance(new_name_or_name_dict, dict):
            return self.rename_axis(index=new_name_or_name_dict)
        else:
            return super().rename(new_name_or_name_dict)

    def sel(self, indexers=None, drop=False, **indexers_kwargs):
        indexers = indexers or {}
        indexers.update(indexers_kwargs)
        if len(indexers) == 1:
            level, key = list(indexers.items())[0]
            if not isinstance(key, Collection) and not drop:
                # When using .loc[] to select 1 label on 1 level, pandas drops
                # the level. Use .xs() to avoid this behaviour unless drop=True
                return AttrSeries(self.xs(key, level=level, drop_level=False))

        idx = tuple(indexers.get(l, slice(None)) for l in self.index.names)
        return AttrSeries(self.loc[idx])

    def sum(self, *args, **kwargs):
        obj = super(AttrSeries, self)
        attrs = None

        try:
            dim = kwargs.pop('dim')
        except KeyError:
            dim = list(args)
            args = tuple()

        if isinstance(self.index, pd.MultiIndex):
            if len(dim) == len(self.index.names):
                # assume dimensions = full multi index, do simple sum
                kwargs = {}
            else:
                # pivot and sum across columns
                obj = self.unstack(dim)
                kwargs['axis'] = 1
                attrs = self.attrs
        else:
            if dim != [self.index.name]:
                raise ValueError(dim, self.index.name, self)
            kwargs['level'] = dim

        return AttrSeries(obj.sum(*args, **kwargs), attrs=attrs)

    def squeeze(self, *args, **kwargs):
        kwargs.pop('drop')
        return super().squeeze(*args, **kwargs) if len(self) > 1 else self

    def as_xarray(self):
        return xr.DataArray.from_series(self)

    def transpose(self, *dims):
        return self.reorder_levels(dims)

    def to_dataframe(self):
        return self.to_frame()

    def to_series(self):
        return self

    def align_levels(self, other):
        """Work around https://github.com/pandas-dev/pandas/issues/25760.

        Return a copy of *obj* with common levels in the same order as *ref*.

        .. todo:: remove when Quantity is xr.DataArray, or above issues is
           closed.
        """
        if not isinstance(self.index, pd.MultiIndex):
            return self
        common = [n for n in other.index.names if n in self.index.names]
        unique = [n for n in self.index.names if n not in common]
        return self.reorder_levels(common + unique)
