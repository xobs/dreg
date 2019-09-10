from migen import *
from litex.soc.interconnect.csr import *

"""dreg: Documented Registers

This implements wrapped CSR storage types that provide field-level
documentation.  These registers may be instantiated in a method
similar to CSRStorage and CSRStatus registers, except they are
more concerned with field-level attributes.

This is important for `STATUS` and `CONTROL` registers, which are
usually comprised of several independent fields.  With a traditional
CSR, such registers simply expose an opaque `storage` or `status` field.

A `dreg` has enough information to produce a datasheet.

Attributes:
    _re (:obj:`Signal()`): Strobed when `_storage` is updated.
        The `_we` signal indicates that the `_storage` has just been
        written to from the CSR bus, meaning you can now read from it.
    _re (:obj:`Signal()`): Strobe this when you update `_storage`.
        This signal is only present when you create a `Reg` that is
        both readable and writeable.  Use this to copy the contents
        of the `Reg` from `_status` to `_storage` so that the CPU
        can get the new values.
    _storage (:obj:`Signal(n)`): Raw writeable storage signals.
        This attribute can be used to access the entire :obj:`Signal`
        object directly.  However, it is preferrable to use the
        convenience methods instead.
    _status (:obj:`Signal(n)`): Raw readable signals.
        This attribute can be used to access the entire :obj:`Signal`
        object directly.  However, it is preferrable to use the
        convenience methods instead.
    _reset (:obj:`Signal()`): Reset the storage object.
        If constructed with `reset=True`, this signal can be written
        in order to reset the underlying storage, even if the storage
        is not normally writeable.
    _csr_storage (:obj:`CSRStorage`): Internal backing storage object
    _csr_status (:obj:`CSRStatus`): Internal backing storage object

"""

class Reg(Module, AutoCSR):
    """Implements a Register as a CSRStorage or CSRStatus, as necessary"""

    def __init__(self, size=None, *fields, name=None, description=None, readable=False, writeable=False, resettable=False, atomic=False):
        """Create a memory-mapped Register.

        Depending on the value of `readable` and `writeable`, Reg will be backed by
        either a :obj:`CSRStorage` or :obj:`CSRStatus`.  It will then create
        convenience wrappers around this core storage.

        It is possible to create registers that are both `readable` and `writeable`,
        in which case convenience methods will be prefixed with `i_` and `o_`.

        Args:
            size (int) (optional): How wide to make this register
                A width may be specified.  If none is specified, then the width is
                set to the total size of all `fields`.
                If no fields are specified, then the width must be specified.
            name (:obj:`str`): The name of register.
                The name should be all lowercase, and be a valid Python identifier.
                The name must not start with "_".  This will be transformed into
                all-caps for certain operations.  If no name is specified, :obj:`Reg`
                will attempt to infer it, but may raise an error if it can't figure out
                what to call itself.
            description (:obj:`str`): An overview of thsi register
                This field contains Markdown data that describes this register's
                overall contents.
            *fields (:obj:`list` of :obj:`Field`): All fields of this register.
                Each entry in the list is a single :obj:`Field`.  The order of the
                fields represents the order in which they will be added to the
                :obj:`Reg`.  It is possible to have disjoint fields by setting the
                `offset` parameter, however it is an error to have overlapping
                :obj:`Field` regions.
                If there are no fields, then a single Field is created and the width
                must be specified.
            readble (bool): `True` if this :obj:`Reg` should be readable by the user.
                If a Reg is `readable` but not `writeable`, then it will be backed
                by a :obj:`CSRStatus`.  If it is both `readable` and `writeable`
                then it will be backed by a :obj:`CSRStorage`.
            writeable (bool): `True` if this :obj:`Reg: should be writeable by the user.
                Note that `writeable` is from the perspective of the user of the design,
                i.e. from the CPU or the Wishbone bridge.  Therefore, a register that
                is writeable can only be written from the CPU and read from Migen.
            resettable (bool): `True` if a reset should be inserted.
                To make a write-only register resettable, set `reset=True`.
            atomic (bool): `True` if writes are to be atomic.
                If writes are atomic, then they only take effect when the last register
                is updated.  `atomic` has no meaning for registers that are only `readable`.
        """
        bits = []
        current_offset = 0

        self._name = get_obj_var_name(name)
        if self._name is None:
            raise ValueError("Cannot extract Reg name from code -- please provide one by passing `name=` to the initializer")

        _fields = []
        print(dir(fields))
        print(fields.__class__)
        print(len(fields))
        # The first argument can be either a number or a Field.  If it's a Field,
        # transform the size into "None" (i.e. "guess"), then fold the size into
        # the fields list
        size_is_field = False
        if not isinstance(size, int):
            print("Size is not int, it's {}".format(size.__class__))
            size_is_field = True
        for f in fields:
            print("Copying field: {}".format(f))
            _fields.append(f)
        if len(_fields) == 0 and not size_is_field:
            print("Adding default field")
            if writeable:
                _fields.append(Field("storage", size=size, offset=0, hidden=True))
            elif readable:
                _fields.append(Field("status", size=size, offset=0, hidden=True))
        if size_is_field:
            _fields.insert(0, size)
            size = None

        # Figure out how many bits we'll need
        for field in _fields:
            if field.offset is not None:
                current_offset = field.offset
            field.offset = current_offset
            for bit in range(current_offset, current_offset + field.size):
                while len(bits) <= bit:
                    bits.append(None)
                if len(bits) == bit and bits[bit] is not None:
                    raise ValueError("Register has overlapping fields: {} overlaps with {} at bit {}".format(field.name, bits[bit].name, bit))
                bits[bit] = field
            current_offset = current_offset + field.size

        # Add the appropriate litex storage primative
        status_prefix = ""
        storage_prefix = ""
        if not readable and not writeable:
            raise ValueError("Reg was neither readable or writeable -- initialize class with readable=True or writeable=True")
        elif readable and not writeable:
            self._csr_status = CSRStatus(len(bits), name=self._name)
            self._status = self._csr_status.status
        elif not readable and writeable:
            storage = CSRStorage(len(bits), name=self._name, atomic_write=atomic)
            if resettable:
                self._csr_storage = ResetInserter()(storage)
                self._reset = self._csr_storage.reset
            else:
                self._csr_storage = storage
            self._storage = self._csr_storage.storage
            self._re = self._csr_storage.re
        elif readable and writeable:
            storage = CSRStorage(len(bits), name=self._name, write_from_dev=True, atomic_write=atomic)
            if resettable:
                self._csr_storage = ResetInserter()(storage)
            else:
                self._csr_storage = storage
                self._reset = self._csr_storage.reset
            self._storage = self._csr_storage.storage
            self._status = self._csr_storage.dat_w
            self._re = self._csr_storage.re
            self._we = self._csr_storage.we
            status_prefix = "o_"
            storage_prefix = "i_"
        else:
            raise ValueError("Unrecognized combination of readable and writeable")

        seen_fields = {}
        storage_signal_array = []
        # Map the fields to something we can Cat() together
        for field in bits:
            if field is None:
                storage_signal_array.append(Signal())
            if field.name in seen_fields:
                continue
            if readable:
                s = Signal(field.size)
                s.eq(self._status[field.offset:field.offset+field.size])
                exec("self.{}{} = s".format(status_prefix, field.name))
                seen_fields[field.name] = 1
            if writeable:
                s = Signal(field.size)
                storage_signal_array.append(s)
                if field.pulse:
                    sp = Signal()
                    self.comb += sp.eq(s & self._re)
                    s = sp
                exec("self.{}{} = s".format(storage_prefix, field.name))
                seen_fields[field.name] = 1
        if writeable:
            self.comb += self._storage.eq(Cat(*storage_signal_array))

class RegStorage(Reg):
    def __init__(self, *fields, **kwargs):
        kwargs['writeable']=True
        Reg.__init__(self, *fields, **kwargs)

class RegStatus(Reg):
    def __init__(self, *fields, **kwargs):
        kwargs['readable']=True
        Reg.__init__(self, *fields, **kwargs)

class Field:
    """Describes a Field for use in a :obj:`Reg`"""
    def __init__(self, name, size=1, offset=None, description=None, values=None,
                             pulse=False, readable=True, writeable=True, hidden=False):
        """Create a :obj:`Field`

        Args:
            name (:obj:`str`): The name of this field.
                Names must be valid Python identifiers, and must be all lower-case.
                They must not begin with "_".
            size (int): How many bits wide to make this field.
                Fields must be at least one bit wide, and have no maximum width.
            offset (int): Where to position this field within the :obj:`Reg`.
                If an offset is specified, it must be >= 0.  Offsets may not overlap.
                If you specify an offset, then all fields that follow will use that offset.
                For example, if you specify a 1-bit wide Field at offset 4, then the
                next Field will be placed at offset 5 unless otherwise specified.
            description (:obj:`str`): A description of this field.
                Use this to provide a freeform description of this particular field.
                This will be used when the datasheet is generated in order to
                describe this particular field, so be descriptive.
            values (:obj:`list` of (:obj:`str`, :obj:`str`)): A list of supported values.
                If this is specified, a table will be generated containing the values
                you specify, in the order you specify.  These are freeform,
                and will be displayed in the order you specify.  They must be tuples
                of (value, description).  For example:
                    [
                        ("0b0000", "disable the timer"),
                        ("0b0001", "slow timer"),
                        ("0b1xxx", "fast timer"),
                    ]
            pulse (bool): `True` if the value is only active for one cycle.
                If `True`, then when this value is written as `1` by the host,
                it will only be `1` for one cycle in the Migen code.  This can be
                useful for reset signals, start signals, or other triggers.
            readable (bool): Used when formatting the register for display.
                The `readable` field is only used for formatting, to indicate if a field
                is write-only or not.  It is possible to have a register that is
                write-only but still readable.
            writeable (bool): Used for formatting the register for display.
            hidden (bool): `True` if this field shouldn't appear on the output.
                This is mostly useful for implied values, where there is one field
                in a register and you'd prefer to put the documentation at the
                register level.
        """
        if not name.isidentifier():
            raise ValueError("{} is not a valid Python identifier".format(name))

        if not isinstance(size, int):
            raise ValueError("'size' is not an int")
        if size < 1:
            raise ValueError("'size' must be >= 1")
        if isinstance(offset, int):
            if offset < 0:
                raise ValueError("'offset' must be >= 0")
        elif offset is not None:
            raise ValueError("'offset' must be an int, or None")
        self.name = name
        self.size = size
        self.offset = offset
        self.description = description
        self.readable = readable
        self.writeable = writeable
        self.pulse = pulse
        self.values = values
        self.hidden = hidden