from migen import *
from migen.fhdl.decorators import ResetInserter
from litex.soc.interconnect.csr import CSRStorage, CSRStatus


def get_size_and_fields(size, fields, default_name):
    """The first argument can be either a number or a Field.  If it's a Field,
    transform the size into "None" (i.e. "guess"), then fold the size into
    the fields list."""
    size_is_field = False
    _fields = []
    if not isinstance(size, int):
        # print("Size is not int, it's {}".format(size.__class__))
        size_is_field = True

    for f in fields:
        # print("Copying field: {}".format(f))
        _fields.append(f)

    if len(_fields) == 0 and not size_is_field:
        # print("Adding default field")
        _fields.append(Field(default_name, size=size, offset=0, hidden=True))
    if size_is_field:
        _fields.insert(0, size)
        size = None
    return (size, _fields)

def get_bit_list(fields):
    bits = []
    current_offset = 0 # Running counter of which bit we're on
    # Figure out how many bits we'll need
    for field in fields:
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
    return bits

class DCSRSignals(dict):
    __getattr__ = dict.__getitem__

class DCSR:
    def make_storage_signals(self, bits):
        signals = DCSRSignals()
        seen_fields = set()

        for field in bits:
            if field is None:
                signals.append(Signal())
                continue
            if field.name in seen_fields:
                continue
            seen_fields.add(field.name)

            signal = Signal(field.size)
            self.comb += signal.eq(self.storage >> field.offset)

            if field.pulse:
                signal_pulsed = Signal(field.size)
                self.comb += signal_pulsed.eq(signal & Replicate(self.re, field.size))
                signals[field.name + "_raw"] = signal
                signals[field.name] = signal_pulsed
            else:
                signals[field.name] = signal
        self.r = signals

    def make_status_signals(self, bits):
        signals = DCSRSignals()
        signal_list = []
        seen_fields = set()

        for field in bits:
            if field is None:
                signal_list.append(Signal())
                continue
            if field.name in seen_fields:
                continue
            seen_fields.add(field.name)

            signal = Signal(field.size)
            signals[field.name] = signal
            signal_list.append(signal)
        self.w = signals
        self.comb += self.status.eq(Cat(*signal_list))


class DCSRStorage(CSRStorage, DCSR):
    """DCSRStorage: Documented CSRStorage object

    This implements wrapped CSRStorage types that provide field-level
    documentation.  These registers may be instantiated in a method
    similar to CSRStorage and CSRStatus registers, except they are
    more concerned with field-level attributes.

    This is important for `STATUS` and `CONTROL` registers, which are
    usually comprised of several independent fields.  With a traditional
    CSR, such registers simply expose an opaque `storage` or `status` field.

    A :obj:`DCSRStorage` has enough information to produce a datasheet.

    Attributes:
        re (:obj:`Signal()`): Strobed when `storage` is updated.
            The `_we` signal indicates that the `storage` has just been
            written to from the CSR bus, meaning you can now read from it.
        we (:obj:`Signal()`): Strobe this when you update `storage`.
            This signal is only present when you create a :obj:`DCSRStorage`
            object that is both readable and writeable.  Use this to copy
            the contents of the :obj:`Signal` from `status` to `storage` so
            that the CPU can get the new values.
        storage (:obj:`Signal(n)`): Raw writeable storage signals.
            This attribute can be used to access the entire :obj:`Signal`
            object directly.  However, it is preferrable to use the
            convenience methods instead.
        status (:obj:`Signal(n)`): Raw readable signals.
            This attribute can be used to access the entire :obj:`Signal`
            object directly.  However, it is preferrable to use the
            convenience methods instead.
        reset (:obj:`Signal()`): Reset the storage object.
            If constructed with `reset=True`, this signal can be written
            in order to reset the underlying storage, even if the storage
            is not normally writeable.
        r (:obj:`dict` of :obj:`Signal()`): Dictionary containing all incoming `Field`s.
            If this CSR is `readable`, then this dictionary contains one
            entry for each :obj:`Field` that is present.  These are all readable.
        w (:obj:`dict` of :obj:`Signal()`): Dictionary containing all outgoing `Field`s.
            If this CSR is `writable`, then this dictionary contains one
            entry for each :obj:`Field` that is present.  These are all writeable.
    """
    def __init__(self,
                 size=None, *fields, name=None, description=None,
                 writeable=False, resettable=False, reset=0,
                 atomic=False):
        """Create a memory-mapped DCSRStorage.

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
            description (:obj:`str`): An overview of this register
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
            reset (:obj:`Signal()`): Default value at reset
                This is the value that this CSR will be initialized to at reset.
            writeable (bool): `True` if this :obj:`DCSRStorage`: should be writeable from Migen.
                Note that `writeable` is from the perspective of Migen. Therefore, a register that
                is not writeable can only be written from the CPU and read from Migen.
            resettable (bool): `True` if a reset should be inserted.
                To make a read-only register resettable, set `reset=True`.
            atomic (bool): `True` if writes are to be atomic.
                If writes are atomic, then they only take effect when the last register
                is updated.  `atomic` has no meaning for registers that are only `readable`.
        """
        
        (size, fields) = get_size_and_fields(size, fields, "storage")
        bits = get_bit_list(fields)

        try:
            CSRStorage.__init__(self, len(bits), reset=reset, name=name,
                                        atomic_write=atomic, write_from_dev=writeable)
        except Exception as e:
            raise ValueError("Cannot extract Reg name from code -- please provide one by passing `name=` to the initializer: {}".format(e))

        if resettable:
            self.reset = Signal(1, reset=0)
            self.sync += If(self.reset, self.storage_full.eq(0))
        
        if writeable:
            self.status = self.storage.dat_w
            self.make_status_signals(bits)

        self.make_storage_signals(bits)

class DCSRStatus(CSRStatus, DCSR):
    """DCSRStatus: Documented CSRStatus object

    This implements wrapped CSRStatus types that provide field-level
    documentation.  These registers may be instantiated in a method
    similar to CSRStorage and CSRStatus registers, except they are
    more concerned with field-level attributes.

    This is important for `STATUS` and `CONTROL` registers, which are
    usually comprised of several independent fields.  With a traditional
    CSR, such registers simply expose an opaque `storage` or `status` field.

    A :obj:`DCSRStatus` has enough information to produce a datasheet.

    Attributes:
        status (:obj:`Signal(n)`): Raw readable signals.
            This attribute can be used to access the entire :obj:`Signal`
            object directly.  However, it is preferrable to use the
            convenience methods instead.
        reset (:obj:`Signal()`): Reset the storage object.
            If constructed with `reset=True`, this signal can be written
            in order to reset the underlying storage, even if the storage
            is not normally writeable.
        o (:obj:`dict` of :obj:`Signal()`): Dictionary containing all outgoing `Field`s.
            If this CSR is `wirable`, then this dictionary contains one
            entry for each :obj:`Field` that is present.  These are all writeable.
    """
    def __init__(self,
                 size=None, *fields, name=None, reset=0, description=None):
        """Create a memory-mapped DCSRStatus.

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
            reset (:obj:`Signal(n)`): Value of the :obj:`CSRStatus` right after reset.
                The :obj:`CSRStatus` will immediately take its value after the first
                cycle, however it can be useful to provide an initialization value here
                for simulation purposes.
            description (:obj:`str`): An overview of this register
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
        """
        
        (size, fields) = get_size_and_fields(size, fields, "status")
        bits = get_bit_list(fields)

        try:
            CSRStatus.__init__(self, len(bits), reset=reset, name=name)
        except Exception as e:
            raise ValueError("Cannot extract CSRStatus name from code -- please provide one by passing `name=` to the initializer: {}".format(e))
        self.make_status_signals(bits)

class Field:
    """Describes a Field for use in a :obj:`CSRStorage` or :obj:`CSRStatus`"""
    def __init__(self, name, size=1, offset=None, description=None, values=None,
                             pulse=False, readable=True, writeable=True, hidden=False):
        """Create a :obj:`Field`

        Args:
            name (:obj:`str`): The name of this field.
                Names must be valid Python identifiers, and must be all lower-case.
            size (int): How many bits wide to make this field.
                Fields must be at least one bit wide, and have no maximum width.
            offset (int): Where to position this field within the :obj:`DCSR`.
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