from pydantic import BaseModel
from datetime import datetime

class InventoryBase(BaseModel):
    """ The InventoryBase schema aerves as the parent for our API validation. 
        It has two required fields, name of the item and quantity of the Item. """
    name : str
    quantity : int

class InventoryCreate(InventoryBase):
    """ The InventoryCreate schema is a child schema inheriting from the InventoryBase schema.
        This will be used in the route for creating a new inventory item. """
    pass

class InventoryUpdate(BaseModel):
    """ The InventoryUpdate schema is a standalone schema. It has a non-nullable field quantity,
        including that only the quantity field of the inventory item can be updated."""
    quantity : int


class InventoryResponse(InventoryBase):
    """ The InventoryResponse schema represents how the inventory data is rendered from the database to the user.
      It is a child schema of the InventoryBase schema. The Config class with the from_attributes = True 
      allows pydantic work seamlessly with SQLAlchemy models."""
    id : int
    updated_at : datetime

    class config:
        from_attributes = True

