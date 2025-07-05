import sys

import pandas as pd

class Technology():
  """
  Object that holds Technology data and techno-economic calculations.
  """
  def __init__(
      self,
      name           : str,
      product        : str,
      design_data    : pd.DataFrame(),
      financial_data : pd.DataFrame(),
      initial          : bool = True,
      output         : float = 1.0,
      ):
    """
    Instantiate a Technology, store data, and calculate basic techno-economic results.
    
    Parameters
    ----------
    name : str
      Name of the Technology. Code will break if name is not present in the Design dataset.
    product : str
      Name of the primary product for calculating per-unit production cost. Code will break
      if this product is not present in the Design dataset.
    design_data : pandas.DataFrame
      Dataset of Technology design data.
    financial_data : pandas.DataFrame
      Dataset of financial data used for every Technology.
    initial : Bool, Default = True
      For Barrier Film process only. Set to True if production of virgin film is being modeled. Set
      to False if this process is part of a closed loop EoL supply chain. If False, raw material costs
      for nylon 6 and polyethylene are set to zero because these materials are obtained from STRAP.
    output : float, default=1.0
      Amount (lbs) of output from this Technology required for the Scenario-level functional unit.      
    
    Attributes
    ----------
    name : str
      Name of the Technology.
    design_data : pandas.DataFrame
      Subset of the design data specific to this Technology.
    product : str
      Name of the Technology's primary product.
    finan : pandas.DataFrame
      Financial data (complete dataset).
    op_hrs_yr : int
      Number of hours per year the Technology operates.
    onetime_costs : pandas.DataFrame
      TEA result (USD): One-time capital costs.
    output : float
      Amount (lbs) of primary product being generated.
    annual_costs : list of pandas.DataFrame
      TEA result (USD/yr): All annualized costs for this Technology, including capital.
      Annual costs do NOT scale with output - they reflect the process scale 
      defined in the input TEA dataset.
    output_amounts : pandas.DataFrame
      TEA result (lbs): Amounts of all products generated (primary and co-product).
    normalized_costs : list of pandas.DataFrame
      TEA result (USD/lb): Technology costs normalized to output of primary product.
    annual_revenue : pandas.DataFrame
      TEA result (USD/yr): Annualized revenue from sale of co-products.
    normalized_revenue : pandas.DataFrame
      TEA result (USD/lb): Revenue normalized to output of primary product.
    net_normalized_costs : float
      TEA result (USD/lb): Net cost (cost minus revenue) per output of primary product.
    production_cost : float
      TEA result (USD): Net cost (cost minus revenue) for total output of primary product.

    Returns
    -------
    None
    """
    # store technology name as attribute
    self.name = name

    self.output = output

    # Only keep technology-relevant rows from the design dataset
    self.design = design_data.loc[design_data.Technology == name]
    if self.design.empty:
      sys.exit(f'Technology {name} not found in design dataset.')
    
    # Check that the primary product exists in this technology's design dataset
    if not any(self.design.Index.loc[self.design.Variable == 'Output'].isin([product])):
      sys.exit(f'Product {product} not found in technology {name} design dataset.')
    else:
        self.product = product   
    
    # Financial data applies to all technologies so keep all of it
    self.finan = financial_data

    # If we're modeling barrier film produced from STRAP-derived materials, there are no
    # costs for the nylon and polyethylene materials
    if not initial:
      self.finan.loc[
        (self.finan.Category == 'Cost') &
        (self.finan.Variable == 'Input') & 
        (self.finan.Index.isin( ['Nylon 6','Polyethylene'])), 'Value'] = 0.0
    
    # Operating hours per year are used in multiple calculations - create an attribute
    self.op_hrs_yr = self.finan.Value.loc[
      self.finan.Variable == 'Operating Hours'
    ].values
    
    # Assemble one-time costs into dataframe
    self.onetime_costs = pd.concat([
      self.capital()[0]
    ])

    # Assemble annual(ized) costs into dataframe
    self.annual_costs = pd.concat([
      self.capital()[1],
      self.raw_material(),
      self.labor(),
      self.utilities(),
      self.wastes(),
      self.other_costs()
    ])

    # Get the annual production amounts by output
    # Includes primary and co-products
    self.output_amounts = self.production()
    
    # Calculate costs per mass of primary output product
    self.normalized_costs = self.annual_costs.copy()
    self.normalized_costs.Value = self.normalized_costs.Value / self.output_amounts.Actual.values[0]

    # Get revenue streams by coproduct (annual)
    if name not in ['Barrier Film','Mechanical and Solvent Cleaning', 'Solvent Treatment and Precipitation']:
      self.annual_revenue = self.product_revenue()
    else:
      self.annual_revenue = self.coproduct_revenue()

    self.normalized_revenue = self.annual_revenue.copy()
    self.normalized_revenue.Value = self.normalized_revenue.Value / self.output_amounts.Actual.values[0]
    
    self.net_normalized_costs = self.normalized_costs.Value.sum() - self.normalized_revenue.Value.sum()
    # Calculate production costs per unit primary product and scale by
    # required output from this Technology
    self.production_cost = self.output * self.net_normalized_costs
    

  def capital(self):
    """
    Calculate annualized and one-time purchase cost of equipment, cost of installation, and annual maintenance.

    Parameters
    ----------
    None
    
    Returns
    -------
    List of pandas.DataFrame
        Purchase cost, annualized purchase cost, installed cost, and annual maintenance cost
        of all capital. First element has one time costs, second element has annual(ized) costs.
    """
    # Calculate purchase costs per type of capital from scale and unit costs
    _cap_cost = self.design[['Index','Value']].loc[self.design.Variable == 'Capital scale'].merge(
      self.finan[['Index','Value']].loc[self.finan.Variable == 'Capital'],
      on='Index',
      how='left'
    )
    
    _cap_cost['purch'] = _cap_cost.Value_x * _cap_cost.Value_y     
    
    # Calculate installed equipment cost with installation multiplier
    _cap_cost['installed'] = (1 + self.finan.Value.loc[self.finan.Index == 'Installation'].values) * _cap_cost.purch
    
    _cap_cost.drop(columns=['Value_x','Value_y'], inplace=True)
    
    # Calculate annualized capital cost (purchase + installation)
    _cap_ann = _cap_cost.merge(
      self.design[['Index','Value']].loc[self.design.Variable=='Capital depreciation'],
      on='Index'
    )
    
    # Annualize the purchase cost using straight-line depreciation
    _cap_ann['cost_ann'] = _cap_ann.installed / _cap_ann.Value
    
    # Calculate annual capital maintenance costs with maintenance multiplier
    _maint_ann = self.finan.Value.loc[self.finan.Index == 'Maintenance'].values * _cap_cost.purch
    
    return [
      # One time costs
      pd.DataFrame().from_dict(
        data = {'Capital Purchased': sum(_cap_cost.purch),
              'Capital Installed': sum(_cap_cost.installed)},
        orient='index',
        columns=['Value']
      ).reset_index(),
      # Annual costs
      pd.DataFrame().from_dict(
        data = {'Capital, Annualized': sum(_cap_ann.cost_ann),
              'Maintenance': sum(_maint_ann)},
        orient='index',
        columns=['Value']
      ).reset_index()
    ]

        
  def raw_material(self):
    """    
    Calculate annual cost of all non-energy inputs to the Technology.

    Parameters
    ----------
    None

    Returns
    -------
    pandas.DataFrame
        Annual cost of all raw materials
    """
    # Merge input amounts from design with input unit costs from financials
    _mats = self.design[['Index','Value']].loc[(self.design.Variable == 'Input') &
                                               (self.design.Index != 'Contingency')].merge(
      self.finan[['Index','Value']].loc[self.finan.Variable == 'Input'],
      on='Index'
    )

    # calculate hourly cost per material
    _mats['cost'] = _mats.Value_x * _mats.Value_y

    # return the annual cost sum over all materials
    if self.name != 'Landfilling':
      return pd.DataFrame().from_dict(
        data={'Raw Material': _mats.cost.loc[_mats.Index != 'Barrier film'].sum() * self.op_hrs_yr,
              'Barrier Film': _mats.cost.loc[_mats.Index == 'Barrier film'].sum() * self.op_hrs_yr},
        orient='index',
        columns=['Value']
      ).reset_index()
    else:
      return pd.DataFrame().from_dict(
        data={'Raw Material': 0.0, 'Barrier Film': 0.0},
        orient='index',
        columns=['Value']
      ).reset_index()

    
  def labor(self):
    """
    Calculate annual burdened labor cost of operating the Technology.

    Parameters
    ----------
    None

    Returns
    -------
    pandas.DataFrame
        Annual burdened cost of worker and supervisor labor
    """
    # get person-hours/operating hour from designs and cost per person-hour from financial
    _labor = self.design[['Index','Value']].loc[self.design.Variable == 'Labor'].merge(
      self.finan[['Index','Value']].loc[self.finan.Variable == 'Labor'],
      on='Index'
    )
    
    # calculate hourly cost of each labor type
    _labor['cost'] = _labor.Value_x * _labor.Value_y
    
    # Get working hours per year
    _work_hrs = self.finan.Value.loc[self.finan.Variable == 'Working Hours'].values
    
    # get labor burden multiplier
    _burden = self.finan.Value.loc[
      (self.finan.Category == 'Cost Multiplier') & (self.finan.Variable == 'Labor')
    ].values

    return pd.DataFrame().from_dict(
      data={'Labor': _labor.cost.sum() * _work_hrs * (1 + _burden)},
      orient='index',
      columns=['Value']
    ).reset_index()
    
    
  def utilities(self):
    """
    Calculate annual cost of all energy, energy carrier, and steam inputs to the Technology.
    
    Water ?? - this can be a proxy for "energy" costs if water isn't included
    
    Parameters
    ----------
    None

    Returns
    -------
    pandas.DataFrame
        Annual cost of energy and related inputs
    """
    
    # get utility input rates from designs and unit costs from financial
    _util = self.design[['Index','Value']].loc[self.design.Variable == 'Utilities'].merge(
      self.finan[['Index','Value']].loc[self.finan.Variable == 'Utilities'],
      on='Index'
    )
    
    # calculate hourly cost per utility
    _util['cost'] = _util.Value_x * _util.Value_y
    
    return pd.DataFrame().from_dict(
      data={'Utilities': _util.cost.sum() * self.op_hrs_yr},
      orient='index',
      columns=['Value']
    ).reset_index()
        
        
  def wastes(self):
    """
    Calculate annual landfilling and other disposal costs for Technology wastes.
    
    Based on output amounts and reject rate.
    
    Parameters
    ----------
    None

    Returns
    -------
    pandas.DataFrame
        Annual cost of waste disposal
    """
    # Combine the theoretical output amounts with the output efficienies to
    # account for reject rate
    _waste = self.design[['Index','Value']].loc[self.design.Variable == 'Output'].merge(
      self.design[['Index','Value']].loc[self.design.Variable == 'Output efficiency'],
      on='Index'
    )
    
    # Tipping fee - currently only non-hazardous waste
    _tip_fee = self.finan.Value.loc[self.finan.Index == 'Waste disposal'].values
    
    # Calculate annual landfilling costs
    _waste['cost'] = _tip_fee * _waste.Value_x * (1 - _waste.Value_y)

    if self.name != 'Landfilling':
      return pd.DataFrame().from_dict(
        data={'Waste Disposal': _waste.cost.sum() * self.op_hrs_yr},
        orient='index',
        columns=['Value']
      ).reset_index()
    else:
      _mats = self.design[['Index','Value']].loc[
        (self.design.Variable == 'Input') &
        (self.design.Index != 'Contingency')].merge(
          self.finan[['Index','Value']].loc[self.finan.Variable == 'Input'],
          on='Index'
      )
      _mats['cost'] = _mats.Value_x * _mats.Value_y

      return pd.DataFrame().from_dict(
        data={'Waste disposal': _mats.cost.sum() * self.op_hrs_yr},
        orient='index',
        columns=['Value']
      ).reset_index()


    
  def other_costs(self):
    """
    Get contingency cost from Financial.

    Parameters
    ----------
    None
    
    Returns
    -------
      Contingency cost for this technology
    """
    
    _contin = self.design[['Index','Value']].loc[self.design.Index == 'Contingency'].merge(
      self.finan[['Index','Value']].loc[self.finan.Index == 'Contingency'],
      on='Index'
    )

    if _contin.empty:
      _contin = pd.DataFrame.from_dict(
        data={'Contingency': 0.0},
        orient='index',
        columns=['Value']
      )
    else:
      _contin['Value'] = _contin.Value_x * _contin.Value_y * self.op_hrs_yr
      _contin.drop(columns=['Value_x','Value_y'], inplace=True)
      _contin.rename(columns={'Index':'index'}, inplace=True)

    return _contin.reset_index()

    
  def production(self):
    """
    Calculate production rate of all outputs.

    This gets used for cost and revenue normalization.

    Parameters
    ----------
    None    
    
    Returns
    -------
    pandas.DataFrame
        Annual production amounts of each output in relevant units
    """
    if any(self.design.Variable == 'Output efficiency'):
      # Combine the theoretical output amounts with the output efficiencies to
      # account for reject rate
      out = self.design[['Index','Value']].loc[self.design.Variable == 'Output'].merge(
        self.design[['Index','Value']].loc[self.design.Variable == 'Output efficiency'],
        on='Index'
      )

      # Calculate actual annual output amounts by output
      out['Actual'] = out.Value_x * out.Value_y * self.op_hrs_yr
      
      # Calculate theoretical annual output amounts by output
      out['Theoretical'] = out.Value_x * self.op_hrs_yr
      
      out.drop(columns=['Value_x', 'Value_y'], inplace=True)
        
    else:
      out = self.design[['Index','Value']].loc[self.design.Variable == 'Output']
      
      out['Actual'] = out.Value * self.op_hrs_yr
      
      # Rename theoretical annual output amounts by output
      out['Theoretical'] = out.Value * self.op_hrs_yr
      
      out.drop(columns=['Value'], inplace=True)
    
    return out
    
    
  def coproduct_revenue(self):
    """
    Calculate revenue streams from non-primary products.

    Uses actual production amounts, not theoretical.
    
    Parameters
    ----------
    None

    Returns
    -------
    rev : pandas.DataFrame
      Annual revenue from co-product(s) produced.
    """
    _out = self.output_amounts.loc[self.output_amounts.Index != self.product]
    if not _out.empty:
      rev = _out.merge(
        self.finan[['Index','Value']].loc[self.finan.Variable == 'Output'],
        on='Index',
        how='left'
      )
      rev['Revenue'] = rev.Value * rev.Actual
      rev.drop(columns=['Actual', 'Theoretical', 'Value'], inplace=True)
      rev.rename(columns={'Revenue': 'Value'}, inplace=True)
      return rev
    else:
      return pd.DataFrame(columns=['Index','Value'])


  def product_revenue(self):
    """
    Calculate revenue streams from primary products.

    Uses actual production amounts, not theoretical.
    
    Parameters
    ----------
    None

    Returns
    -------
    rev : pandas.DataFrame
      Annual revenue from primary product produced.
    """
    _out = self.output_amounts.loc[self.output_amounts.Index == self.product]
    if not _out.empty:
      rev = _out.merge(
        self.finan[['Index','Value']].loc[self.finan.Variable == 'Output'],
        on='Index',
        how='left'
      )
      # output amount is annual, multiply by price to get annual revenue
      rev['Revenue'] = rev.Value * rev.Actual
      rev.drop(columns=['Actual', 'Theoretical', 'Value'], inplace=True)
      rev.rename(columns={'Revenue': 'Value'}, inplace=True)
      return rev
    else:
      return pd.DataFrame(columns=['Index','Value'])