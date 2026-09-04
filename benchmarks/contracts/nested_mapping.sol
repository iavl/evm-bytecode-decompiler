pragma solidity ^0.8.0;
contract NestedMappingFixture { mapping(address => mapping(address => uint256)) internal allowances; function approve(address spender, uint256 value) external { allowances[msg.sender][spender] = value; } }
